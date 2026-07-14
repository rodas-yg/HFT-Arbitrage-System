package com.router.network;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.DatagramChannel;
///hahaha///
/**
 * This can act as a sprouting class for the (circular!) ring buffer.
 * This standalone thread handles physical network IO and calculates latency.
 */
public class Receiver {
    private static void debuff(ByteBuffer buffer) {
        // Read directly from native memory
        long timestamp = buffer.getLong(0);
        double bidPrice = buffer.getDouble(8);
        double bidQty = buffer.getDouble(16);
        double askPrice = buffer.getDouble(24);
        double askQty = buffer.getDouble(32);
        long volatility = buffer.getLong(16);

        // Zero-allocation epoch alignment.
        long javaTime = System.currentTimeMillis() * 1_000_000L;
        long latency = javaTime - timestamp;

        System.out.println("Latency: " + latency + " ns | Bid: $" + bidPrice);
    }

    public static void main(String[] args) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocateDirect(40);
        buffer.order(ByteOrder.BIG_ENDIAN);

        DatagramChannel channel = DatagramChannel.open();
        // Explicitly bind to IPv4 localhost so we don't accidentally listen on IPv6
        channel.bind(new InetSocketAddress("127.0.0.1", 8888));
        channel.configureBlocking(false);

        System.out.println("Java Engine Network Thread listening on IPv4 UDP 127.0.0.1:8888...");
        while (true) {
            buffer.clear();
            SocketAddress address = channel.receive(buffer);
            if (address != null) {
                debuff(buffer);
            }
        }
    }
}