package com.router.engine;


public class Trade {
    public long ingestTimestampNs;

    public double bidPrice;
    public double bidQty;
    public double askPrice;
    public double askQty;

    public void update(long ingestTimestampNs, double bidPrice, double bidQty, double askPrice, double askQty) {
        this.ingestTimestampNs = ingestTimestampNs;
        this.bidPrice = bidPrice;
        this.bidQty = bidQty;
        this.askPrice = askPrice;
        this.askQty = askQty;
    }
}