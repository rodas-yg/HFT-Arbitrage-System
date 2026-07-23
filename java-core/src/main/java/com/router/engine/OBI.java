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

    /** Placeholder for Phase 3 AI signal (received on UDP 8889) */
    private volatile double latestAiSignal = 0.0;

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
                        action = strategyClient.evaluate(microprice, imbalance, latestAiSignal);
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