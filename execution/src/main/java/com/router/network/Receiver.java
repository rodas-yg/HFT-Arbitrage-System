package com.router.network;
import com.router.engine.ConfigManager;
import com.router.engine.OBI;
import com.router.engine.Padding;
import com.router.engine.RingBuffer;
import com.router.engine.Trade;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.DatagramChannel;
///hahaha///
/**
 * This standalone thread handles physical network IO and calculates latency.
 */
public class Receiver {

    public static void main(String[] args) throws IOException {
        RingBuffer ringBuffer = new RingBuffer(1024);
        OBI obi = new OBI(ringBuffer);

        // Start AI Gateway — listens on UDP 8889 for ml.py predictions
        // and continuously overwrites the volatile AI signal in OBI
        obi.startAiReceiver();

        ConfigManager config = ConfigManager.getInstance();
        if ("KALSHI".equals(config.getExecutionMode())) {
            obi.startKalshiReceiver();
        }

        Thread strategyThread = new Thread(obi);
        strategyThread.start();

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
                long timestamp = buffer.getLong(0);
                double bidPrice = buffer.getDouble(8);
                double bidQty = buffer.getDouble(16);
                double askPrice = buffer.getDouble(24);
                double askQty = buffer.getDouble(32);
                ringBuffer.publish(timestamp, bidPrice, bidQty, askPrice, askQty);
            }
        }
    }
}