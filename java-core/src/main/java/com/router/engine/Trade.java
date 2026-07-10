packge com.router.engine;
//data carrier
public class Trade {
    public long inTime;
    public long bidPrice;
    public long bidVolume;
    public long askPrice;
    public long askVolume;

    public void update(long inTime, long bidPrice, long bidVolume, long askPrice, long askVolume) {
        this.inTime = inTime;
        this.bidPrice = bidPrice;
        this.bidVolume = bidVolume;
        this.askPrice = askPrice;
        this.askVolume = askVolume;
    }
}