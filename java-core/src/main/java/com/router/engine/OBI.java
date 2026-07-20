package com.router.engine;

import java.io.IOException;

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

    @Override
    public void run() {
        System.out.println("Strategy thread started. Waiting for data...");

        // Try to connect to OCaml on startup
        connectToOCaml();

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

                messageCount++;
                if (messageCount % 100 == 0) {
                    System.out.printf("Latency: %,d ns | Microprice: $%.2f | Imbalance: %.3f | Strategy: %s%n",
                            latencyNs, microprice, imbalance, action);
                }

            }
        }
    }
}