package com.router.engine;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.VarHandle;

/**
 * RING BUFFER SEQUENCE COUNTERS & FALSE SHARING PADDING
 * * 1. producerSequence (Core 1 / The Catcher)
 * An infinite counter tracking the total number of items written to the buffer.
 * Used to calculate the next array write index and to prevent overwriting unread
 * data when the buffer is full.
 * * 2. consumerSequence (Core 2 / The Brain)
 * An infinite counter tracking the total number of items successfully read and processed.
 * Used to calculate the next array read index and to pause reading when the buffer is empty.
 * * 3. Cache Line Padding (Preventing False Sharing)
 * Modern CPUs load memory into private L1 caches in 64-byte chunks (Cache Lines).
 * If the producer and consumer sequences sit adjacently in memory, they share the
 * same cache line. When one core updates its sequence, hardware protocols force the
 * other core to delete its cache, destroying performance.
 * * By injecting 56 bytes of dummy padding between the sequences, we force them into
 * physically separate 64-byte cache lines. This ensures Core 1 and Core 2 can operate
 * at max speed without their private caches constantly invalidating each other.
 */

public class Padding {
    long p1, p2, p3, p4, p5, p6, p7; //7*8=56 bytes of memory (the rest 8 wil be the actual value)

    private volatile long sequence = 0; //volatile forces the cpu to communicate with L3 so that it doesnt miss the updates from the first core
    long p8, p9, p10, p11, p12, p13, p14;//back padding

    private static final VarHandle SEQUENCE_HANDLE;
    static { //static blocks are run before any other objects are created
        try{
            SEQUENCE_HANDLE = MethodHandles.lookup().findVarHandle(Padding.class, "sequence", long.class);
        } catch (ReflectiveOperationException e) {
            throw new Error(e);
        }
    }

    public long getAcquire() {
        return (long) SEQUENCE_HANDLE.getAcquire(this);
    }

    public void setRelease(long nextSequence) {
        SEQUENCE_HANDLE.setRelease(this, nextSequence);
    }

}
