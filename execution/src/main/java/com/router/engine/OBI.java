package com.router.engine;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.DatagramChannel;

public class OBI implements Runnable {
    private final RingBuffer ringBuffer;
    private long messageCount = 0;

    /**
     * Optional connection to the OCaml Strategy Engine.
     * Null if OCaml is not running — OBI continues without strategy evaluation.
     */
    private StrategyClient strategyClient = null;

    /**
     * AI confidence signal from ml.py (received on UDP 8889).
     * Range: [-1.0, 1.0] where positive = bullish, negative = bearish.
     * Computed as prob_up - prob_down from the LSTM softmax output.
     * Volatile for lock-free cross-thread visibility.
     */
    private volatile double latestAiSignal = 0.0;
    
    private volatile double latestKalshiBid = 0.0;
    private volatile double latestKalshiAsk = 0.0;

    /** AI prediction receive buffer: 16 bytes = 2 × float64 big-endian */
    private static final int AI_PACKET_SIZE = 16;
    private static final int AI_PORT = 8889;

    /** Kalshi receive buffer: 24 bytes = uint64 + 2 × float64 big-endian */
    private static final int KALSHI_PACKET_SIZE = 24;
    private static final int KALSHI_PORT = 8891;

    /**
     * UDP broadcast channel for telemetry (Port 9000).
     * Sends a 41-byte binary packet per tick to the Python telemetry recorder:
     *   [timestamp_ns:8B | microprice:8B | imbalance:8B | ai_confidence:8B | strategy_action:1B]
     */
    private DatagramChannel telemetryChannel = null;
    private ByteBuffer telemetryBuf = null;
    private static final InetSocketAddress TELEMETRY_DEST =
            new InetSocketAddress("127.0.0.1", 9000);
    private static final int TELEMETRY_PACKET_SIZE = 33; // 4×8 + 1

    public OBI(RingBuffer ringBuffer) {
        this.ringBuffer = ringBuffer;
    }

    /**
     * Attempt to connect to the OCaml Strategy Engine.
     * Called once at startup. If OCaml isn't running, we log and continue.
     */
    private void connectToOCaml() {
        try {
            strategyClient = new StrategyClient();
        } catch (IOException e) {
            System.out.println("[Java] OCaml Strategy Engine not available — running without strategy evaluation");
            System.out.println("[Java] Start OCaml with: dune exec strategy_server");
            strategyClient = null;
        }
    }

    /**
     * Initialize the UDP telemetry broadcast channel (Port 9000).
     * Fire-and-forget — if no listener is running, packets are silently dropped.
     */
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

    /**
     * Broadcast a telemetry packet via UDP (fire-and-forget).
     */
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
            // Silently drop — telemetry is best-effort
        }
    }

    /**
     * Start a background daemon thread to receive AI predictions from ml.py.
     *
     * Listens on UDP 8889 for 16-byte packets:
     *   [prob_down:8B | prob_up:8B] (big-endian float64)
     *
     * Computes net confidence: prob_up - prob_down ∈ [-1.0, 1.0]
     * and stores it in latestAiSignal for the strategy evaluator.
     *
     * If ml.py is not running, this thread blocks harmlessly on receive().
     */
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
                        double probDown = aiBuf.getDouble(0);
                        double probUp   = aiBuf.getDouble(8);
                        latestAiSignal  = probUp - probDown;
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
                        // skip timestamp (8 bytes)
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

        // Try to connect to OCaml on startup
        connectToOCaml();

        // Initialize telemetry broadcast
        initTelemetry();


        while (true) {
            Trade event = ringBuffer.poll();

            if (event != null) {

                long javaTimeNs = System.currentTimeMillis() * 1_000_000L;
                long latencyNs = javaTimeNs - event.ingestTimestampNs;

                double totalVolume = event.bidQty + event.askQty;

                if (totalVolume == 0) continue;

                double microprice = ((event.bidQty * event.askPrice) + (event.askQty * event.bidPrice)) / totalVolume;

                // Order Book Imbalance
                // Positive = Bullish (More Buyers), Negative = Bearish (More Sellers)
                double imbalance = (event.bidQty - event.askQty) / totalVolume;

                // Evaluate strategy via OCaml (if connected)
                TradeAction action = TradeAction.HOLD;
                if (strategyClient != null && strategyClient.isConnected()) {
                    try {
                        long strategyStart = System.nanoTime();
                        action = strategyClient.evaluate(microprice, imbalance, latestAiSignal, latestKalshiAsk);
                        long strategyLatencyNs = System.nanoTime() - strategyStart;

                        // Log strategy latency periodically
                        if (messageCount % 1000 == 0 && messageCount > 0) {
                            System.out.printf("[Strategy IPC] Round-trip: %,d ns%n", strategyLatencyNs);
                        }
                    } catch (IOException e) {
                        System.out.println("[Java] Lost connection to OCaml: " + e.getMessage());
                        strategyClient = null;
                    }
                }

                // Broadcast telemetry to Python recorder (UDP 9000, fire-and-forget)
                broadcastTelemetry(event.ingestTimestampNs, microprice, imbalance,
                                   latestAiSignal, action);

                messageCount++;
                if (messageCount % 100 == 0) {
                    System.out.printf("Latency: %,d ns | Microprice: $%.2f | Imbalance: %.3f | Strategy: %s%n",
                            latencyNs, microprice, imbalance, action);
                }

            }
        }
    }
}