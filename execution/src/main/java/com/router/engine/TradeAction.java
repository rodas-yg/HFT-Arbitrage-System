package com.router.engine;

/**
 * Trade actions returned by the OCaml Engine.
 * Wire encoding matches OCaml's Wire.encode_action:
 *   Hold = 0x00, Buy = 0x01, Sell = 0x02
 */
public enum TradeAction {
    HOLD, BUY, SELL;

    /**
     * Decode a single byte from the OCaml strategy engine into a TradeAction.
     * Uses a switch expression (Java 21+) for branchless-friendly dispatch.
     *
     * @param b The byte received from OCaml via UDS
     * @return  The corresponding TradeAction, defaulting to HOLD for unknown values
     */
    public static TradeAction fromByte(byte b) {
        return switch (b) {
            case 0x01 -> BUY;
            case 0x02 -> SELL;
            default   -> HOLD;
        };
    }
}
