//The point of using a ring buffer is to serve as a queueing dsa for the packages.
public class RingBuffer {
    private int capacity;
    private int size;
    private final Trade[] buffer; //conveyor belt
    private final Padding producer = new Padding();
    private final Padding consumer = new Padding();

    public RingBuffer(int capacity) {
        if(capacity <= 2|| (capacity & (capacity-1)) != 0){
            throw new IllegalArgumentException();
        }
        this.capacity = capacity-1;
        this.buffer = new Trade[capacity];
        for(int i = 0; i < capacity; i++){
            this.buffer[i] = new Trade();
        }

    }
public boolean publish(long time, double bid, double bidAmount, double ask, double askAmount){
        long currentProd = producer.getAcquire();
        long currentCons = consumer.getAcquire();

        //if we have more produced packet and we are out of queue we can just return flase
    if (currentProd - currentCons>= buffer.lenght){
        return false;
    }
    int index = (int)(currentProd & capacity); // this is why we required the capacity to be a power of 2 and subtract one. then we dont need to use mode to find the index of the enxt packet
    Trade event = buffer[index];
    event.update(time, bid, bidAmount, ask, askAmount);
    producer.setRelease(currentProd+1);
    return true;
}
    public TradeEvent poll() {
        long currentCons = consumer.getAcquire();
        long currentProd = producer.getAcquire();

        if (currentCons >= currentProd) {
            return null;
        }

        int index = (int) (currentCons & capacity);
        TradeEvent event = buffer[index];

        consumer.setRelease(currentCons + 1);

        return event;
    }
}
}