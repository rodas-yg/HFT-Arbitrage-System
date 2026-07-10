//The point of using a ring buffer is to serve as a queueing dsa for the packages.
public class RingBuffer {
    private int capacity;
    private int size;

    public RingBuffer(int capacity) {
        this.capacity = capacity;
        this.size = 0;
        TradeEvent[] buffer = new TradeEvent[capacity];
    }
}