package com.router.engine;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.DatagramChannel;

public class MathEngine implements Runnable {
    private final RingBuffer ringBuffer;
    private long messageCount = 0;

    private DatagramChannel strategyChannel = null;
    private ByteBuffer strategySendBuf = null;
    private ByteBuffer strategyRecvBuf = null;

    private volatile double latestProbDown = 0.0;
    private volatile double latestProbUp = 0.0;
    
    private volatile double latestKalshiBid = 0.0;
    private volatile double latestKalshiAsk = 0.0;

    private static final int AI_PACKET_SIZE = 16;
    private static final int AI_PORT = 8889;

    private static final int KALSHI_PACKET_SIZE = 24;
    private static final int KALSHI_PORT = 8891;

    private DatagramChannel telemetryChannel = null;
    private ByteBuffer telemetryBuf = null;
    private static final InetSocketAddress TELEMETRY_DEST =
            new InetSocketAddress("127.0.0.1", 9000);
    private static final int TELEMETRY_PACKET_SIZE = 33; // 4×8 + 1
    
    private TradingMode executionMode;

    public MathEngine(RingBuffer ringBuffer) {
        this.ringBuffer = ringBuffer;
        this.executionMode = ConfigManager.getInstance().getExecutionMode();
    }

    private void connectToOCaml() {
        try {
            strategyChannel = DatagramChannel.open();
            strategyChannel.connect(new InetSocketAddress("127.0.0.1", 8890));
            strategyChannel.configureBlocking(true);
            
            // 1 byte mode + 5 doubles max = 41 bytes
            strategySendBuf = ByteBuffer.allocateDirect(41);
            strategySendBuf.order(ByteOrder.BIG_ENDIAN);
            
            strategyRecvBuf = ByteBuffer.allocateDirect(1);
            
            System.out.println("[Java] Connected to OCaml Strategy Engine on UDP 127.0.0.1:8890");
        } catch (IOException e) {
            System.out.println("[Java] OCaml Strategy Engine not available — running without strategy evaluation");
            strategyChannel = null;
        }
    }

    private void initTelemetry() {
        try {
            telemetryChannel = DatagramChannel.open();
            telemetryChannel.configureBlocking(false);
            telemetryBuf = ByteBuffer.allocateDirect(TELEMETRY_PACKET_SIZE);
            telemetryBuf.order(ByteOrder.BIG_ENDIAN);
            System.out.println("[Java] Telemetry broadcast initialized on UDP 127.0.0.1:9000");
        } catch (IOException e) {
            System.out.println("[Java] Failed to init telemetry: " + e.getMessage());
            telemetryChannel = null;
        }
    }

    private void broadcastTelemetry(long timestampNs, double microprice,
                                    double imbalance, double aiConfidence,
                                    TradeAction action) {
        if (telemetryChannel == null || telemetryBuf == null) return;
        try {
            telemetryBuf.clear();
            telemetryBuf.putLong(timestampNs);
            telemetryBuf.putDouble(microprice);
            telemetryBuf.putDouble(imbalance);
            telemetryBuf.putDouble(aiConfidence);
            telemetryBuf.put(action == TradeAction.BUY ? (byte) 1
                           : action == TradeAction.SELL ? (byte) 2 : (byte) 0);
            telemetryBuf.flip();
            telemetryChannel.send(telemetryBuf, TELEMETRY_DEST);
        } catch (IOException e) {
        }
    }

    public void startAiReceiver() {
        Thread aiThread = new Thread(() -> {
            try {
                DatagramChannel aiChannel = DatagramChannel.open();
                aiChannel.bind(new InetSocketAddress("127.0.0.1", AI_PORT));
                aiChannel.configureBlocking(true);

                ByteBuffer aiBuf = ByteBuffer.allocateDirect(AI_PACKET_SIZE);
                aiBuf.order(ByteOrder.BIG_ENDIAN);

                System.out.println("[Java] AI receiver listening on UDP 127.0.0.1:" + AI_PORT);

                while (true) {
                    aiBuf.clear();
                    aiChannel.receive(aiBuf);
                    if (aiBuf.position() >= AI_PACKET_SIZE) {
                        latestProbDown = aiBuf.getDouble(0);
                        latestProbUp   = aiBuf.getDouble(8);
                    }
                }
            } catch (IOException e) {
                System.out.println("[Java] AI receiver failed: " + e.getMessage());
            }
        }, "ai-receiver");
        aiThread.setDaemon(true);
        aiThread.start();
    }

    public void startKalshiReceiver() {
        Thread kalshiThread = new Thread(() -> {
            try {
                DatagramChannel kalshiChannel = DatagramChannel.open();
                kalshiChannel.bind(new InetSocketAddress("127.0.0.1", KALSHI_PORT));
                kalshiChannel.configureBlocking(true);

                ByteBuffer kalshiBuf = ByteBuffer.allocateDirect(KALSHI_PACKET_SIZE);
                kalshiBuf.order(ByteOrder.BIG_ENDIAN);

                System.out.println("[Java] Kalshi receiver listening on UDP 127.0.0.1:" + KALSHI_PORT);

                while (true) {
                    kalshiBuf.clear();
                    kalshiChannel.receive(kalshiBuf);
                    if (kalshiBuf.position() >= KALSHI_PACKET_SIZE) {
                        latestKalshiBid = kalshiBuf.getDouble(8);
                        latestKalshiAsk = kalshiBuf.getDouble(16);
                    }
                }
            } catch (IOException e) {
                System.out.println("[Java] Kalshi receiver failed: " + e.getMessage());
            }
        }, "kalshi-receiver");
        kalshiThread.setDaemon(true);
        kalshiThread.start();
    }

    @Override
    public void run() {
        System.out.println("Strategy thread started. Waiting for data...");

        connectToOCaml();
        initTelemetry();

        while (true) {
            Trade event = ringBuffer.poll();

            if (event != null) {
                long javaTimeNs = System.currentTimeMillis() * 1_000_000L;
                long latencyNs = javaTimeNs - event.ingestTimestampNs;

                double totalVolume = event.bidQty + event.askQty;
                if (totalVolume == 0) continue;

                double microprice = ((event.bidQty * event.askPrice) + (event.askQty * event.bidPrice)) / totalVolume;
                double imbalance = (event.bidQty - event.askQty) / totalVolume;

                TradeAction action = TradeAction.HOLD;
                if (strategyChannel != null) {
                    try {
                        long strategyStart = System.nanoTime();
                        
                        strategySendBuf.clear();
                        if (executionMode == TradingMode.BINANCE_ONLY) {
                            strategySendBuf.put((byte) 0x00);
                            strategySendBuf.putDouble(microprice);
                            strategySendBuf.putDouble(imbalance);
                            strategySendBuf.putDouble(latestProbUp);
                            strategySendBuf.putDouble(latestProbDown);
                            strategySendBuf.putDouble(0.0);
                        } else {
                            strategySendBuf.put((byte) 0x01);
                            strategySendBuf.putDouble(microprice);
                            strategySendBuf.putDouble(imbalance);
                            strategySendBuf.putDouble(latestProbUp);
                            strategySendBuf.putDouble(latestProbDown);
                            strategySendBuf.putDouble(latestKalshiAsk); // Uses Polymarket/Kalshi Ask Price
                        }
                        strategySendBuf.flip();
                        
                        strategyChannel.write(strategySendBuf);

                        strategyRecvBuf.clear();
                        strategyChannel.read(strategyRecvBuf);
                        action = TradeAction.fromByte(strategyRecvBuf.get(0));
                        
                        long strategyLatencyNs = System.nanoTime() - strategyStart;

                        if (messageCount % 1000 == 0 && messageCount > 0) {
                            System.out.printf("[Strategy UDP IPC] Round-trip: %,d ns%n", strategyLatencyNs);
                        }
                    } catch (IOException e) {
                        System.out.println("[Java] Lost connection to OCaml: " + e.getMessage());
                        strategyChannel = null;
                    }
                }

                double aiConfidence = latestProbUp - latestProbDown;
                broadcastTelemetry(event.ingestTimestampNs, microprice, imbalance,
                                   aiConfidence, action);

                if (action != TradeAction.HOLD) {
                    System.out.printf("[Java] 🔥 Executing Trade: %s 🔥 | Microprice: $%.2f | Confidence: %.4f%n",
                            action, microprice, aiConfidence);
                }

                messageCount++;
                if (messageCount % 100 == 0) {
                    String mlPred = "FLAT";
                    if (latestProbUp > latestProbDown + 0.2) mlPred = "UP";
                    else if (latestProbDown > latestProbUp + 0.2) mlPred = "DOWN";

                    System.out.printf("Data is being recorded... ML Prediction: %s | Action: %s%n",
                            mlPred, action);
                }
            }
        }
    }
}
