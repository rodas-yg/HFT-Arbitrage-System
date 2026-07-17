package com.router.engine;

public class OBI implements Runnable {
    private final RingBuffer ringBuffer;
    private long messageCount = 0;

    public OBI(RingBuffer ringBuffer) {
        this.ringBuffer = ringBuffer;
    }

    @Override
    public void run() {
        System.out.println("Strategy thread started. Waiting for data...");

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

                messageCount++;
                if (messageCount % 100 == 0) {
                    System.out.printf("Latency: %,d ns | Microprice: $%.2f | Imbalance: %.3f%n",
                            latencyNs, microprice, imbalance);
                }

            }
        }
    }
}