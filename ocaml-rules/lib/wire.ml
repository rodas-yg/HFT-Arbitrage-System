(** wire.ml — Binary serialization/deserialization for IPC

    This module handles the conversion between raw bytes on the Unix Domain
    Socket and OCaml types. The wire protocol is designed for minimal latency:

    Request (Java → OCaml):  24 bytes
      [microprice:f64be | imbalance:f64be | ai_confidence:f64be]

    Response (OCaml → Java): 1 byte
      [0x00 = Hold | 0x01 = Buy | 0x02 = Sell]

    Total wire overhead: 25 bytes per evaluation round-trip.
    All floats are IEEE 754 double-precision, big-endian (network byte order),
    matching Java's [ByteBuffer.putDouble] with [ByteOrder.BIG_ENDIAN].
*)

(** Size of the incoming market state payload in bytes.
    3 fields × 8 bytes per float64 = 24 bytes. *)
let request_size = 24

(** Size of the outgoing trade action response in bytes. *)
let response_size = 1

(** Decode 24 bytes (3 × big-endian float64) into a [market_state].

    Uses [Bytes.get_int64_be] to read raw 64-bit integers, then
    reinterprets them as IEEE 754 doubles via [Int64.float_of_bits].
    This avoids any endianness issues — the bit pattern is preserved
    exactly as Java wrote it.

    @param buf  A [Bytes.t] of length >= 24
    @return     The decoded market state record *)
let decode_market_state (buf : Bytes.t) : Ast.market_state =
  let microprice    = Int64.float_of_bits (Bytes.get_int64_be buf 0) in
  let imbalance     = Int64.float_of_bits (Bytes.get_int64_be buf 8) in
  let ai_confidence = Int64.float_of_bits (Bytes.get_int64_be buf 16) in
  { Ast.microprice; imbalance; ai_confidence }

(** Encode a [trade_action] as a single byte.
    The byte values are chosen to match Java's [TradeAction.fromByte]:
    - Hold = 0x00
    - Buy  = 0x01
    - Sell = 0x02

    @param action  The trade action to encode
    @return        A single [char] (byte) *)
let encode_action (action : Ast.trade_action) : char =
  match action with
  | Ast.Hold -> '\x00'
  | Ast.Buy  -> '\x01'
  | Ast.Sell -> '\x02'

(** Pretty-print a trade action for logging. *)
let string_of_action (action : Ast.trade_action) : string =
  match action with
  | Ast.Hold -> "HOLD"
  | Ast.Buy  -> "BUY"
  | Ast.Sell -> "SELL"

(** Pretty-print a market state for logging. *)
let string_of_market_state (s : Ast.market_state) : string =
  Printf.sprintf "microprice=$%.2f | imbalance=%.4f | ai_conf=%.4f"
    s.microprice s.imbalance s.ai_confidence
