package com.router.engine;

import java.io.IOException;
import java.net.UnixDomainSocketAddress;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.SocketChannel;
import java.nio.file.Path;

/**
 * Ultra-low-latency IPC client for the OCaml Strategy Engine.
 *
 * Connects to the OCaml strategy server via a Unix Domain Socket (UDS)
 * and evaluates trading strategies by sending market state and receiving
 * trade actions.
 *
 * Wire Protocol:
 *   Request  (Java → OCaml): 24 bytes = 3 × float64 big-endian
 *     [microprice:8B | imbalance:8B | ai_confidence:8B]
 *
 *   Response (OCaml → Java): 1 byte
 *     [0x00=Hold | 0x01=Buy | 0x02=Sell]
 *
 * Performance:
 *   - Uses DirectByteBuffer (off-heap) to avoid GC pressure
 *   - Persistent connection — no connect/disconnect per evaluation
 *   - Target round-trip: < 5µs
 *
 * Thread Safety:
 *   NOT thread-safe. Designed to be called from a single thread
 *   (the OBI Math Engine consumer thread).
 */
public class StrategyClient implements AutoCloseable {

    private static final String SOCKET_PATH = "/tmp/gsr_strategy.sock";
    private static final int REQUEST_SIZE = 32;   // 4 × 8 bytes
    private static final int RESPONSE_SIZE = 1;

    private final SocketChannel channel;
    private final ByteBuffer sendBuf;
    private final ByteBuffer recvBuf;

    /**
     * Create a new StrategyClient and connect to the OCaml engine.
     *
     * @throws IOException if the socket file doesn't exist or connection fails
     */
    public StrategyClient() throws IOException {
        UnixDomainSocketAddress address = UnixDomainSocketAddress.of(Path.of(SOCKET_PATH));
        this.channel = SocketChannel.open(address);
        this.channel.configureBlocking(true);

        // Direct (off-heap) buffers — no GC overhead
        this.sendBuf = ByteBuffer.allocateDirect(REQUEST_SIZE);
        this.sendBuf.order(ByteOrder.BIG_ENDIAN);
        this.recvBuf = ByteBuffer.allocateDirect(RESPONSE_SIZE);

        System.out.println("[Java] Connected to OCaml Strategy Engine at " + SOCKET_PATH);
    }

    /**
     * Evaluate the current market state against the OCaml strategy AST.
     *
     * Packs 3 doubles into 24 bytes, sends to OCaml, reads 1 byte back.
     * This method is designed for the hot path — no allocations, no exceptions
     * on the happy path.
     *
     * @param microprice    Volume-weighted midpoint price
     * @param imbalance     Order Book Imbalance ∈ [-1.0, 1.0]
     * @param aiConfidence  ML model confidence ∈ [0.0, 1.0]
     * @param kalshiAsk     Kalshi YES contract ask price
     * @return              The strategy's trade action (BUY, SELL, or HOLD)
     * @throws IOException  if the socket connection is broken
     */
    public TradeAction evaluate(double microprice, double imbalance, double aiConfidence, double kalshiAsk)
            throws IOException {
        // Pack 4 doubles into 32 bytes (big-endian)
        sendBuf.clear();
        sendBuf.putDouble(microprice);
        sendBuf.putDouble(imbalance);
        sendBuf.putDouble(aiConfidence);
        sendBuf.putDouble(kalshiAsk);
        sendBuf.flip();

        // Write to OCaml
        while (sendBuf.hasRemaining()) {
            channel.write(sendBuf);
        }

        // Read 1-byte response
        recvBuf.clear();
        int bytesRead = 0;
        while (bytesRead < RESPONSE_SIZE) {
            int n = channel.read(recvBuf);
            if (n < 0) throw new IOException("OCaml strategy engine disconnected");
            bytesRead += n;
        }

        return TradeAction.fromByte(recvBuf.get(0));
    }

    /**
     * Check if the connection to the OCaml engine is still alive.
     */
    public boolean isConnected() {
        return channel != null && channel.isConnected();
    }

    @Override
    public void close() throws IOException {
        if (channel != null && channel.isOpen()) {
            channel.close();
            System.out.println("[Java] Disconnected from OCaml Strategy Engine");
        }
    }
}
