import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.DatagramChannel;

public class Receiver {
    private static void debuff(ByteBuffer buffer) {
        long timestamp = buffer.getLong(0);
        double bidPrice = buffer.getDouble(8);
        double bidQty = buffer.getDouble(16);
        double askPrice = buffer.getDouble(24);
        double askQty = buffer.getDouble(32);
        long jt = System.nanoTime();
        java.time.Instant now = java.time.Instant.now();
        long javaTime = (now.getEpochSecond() * 1_000_000_000L) + now.getNano();
        long latency = javaTime - timestamp;

        System.out.println("Latency: " + latency);
    }

    public static void main(String[] args) throws IOException {
        //Allocate 40 bytes of memory chunk
        ByteBuffer buffer = ByteBuffer.allocate(40);
        buffer.order(ByteOrder.BIG_ENDIAN);

        DatagramChannel channel = DatagramChannel.open();
        channel.bind(new InetSocketAddress(8888));//this directly puts the data packet in the memory chunk created above
        channel.configureBlocking(false);//allows 24/7 spin at 100% CPU usage constantly checking for new data

        while (true) {
            buffer.clear();
            SocketAddress address = channel.receive(buffer);
            if (address != null) {
                debuff(buffer);
            }
        }
    }

}