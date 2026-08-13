(** wire.ml — Binary serialization/deserialization for IPC
*)

let request_size = 41

let response_size = 1

(** Decode 41 bytes (1 byte mode + 5 × big-endian float64) into a [mode, market_state]. *)
let decode_market_state (buf : Bytes.t) : (int * Ast.market_state) =
  let mode                 = int_of_char (Bytes.get buf 0) in
  let microprice           = Int64.float_of_bits (Bytes.get_int64_be buf 1) in
  let binance_imbalance    = Int64.float_of_bits (Bytes.get_int64_be buf 9) in
  let ai_prediction_up     = Int64.float_of_bits (Bytes.get_int64_be buf 17) in
  let ai_prediction_down   = Int64.float_of_bits (Bytes.get_int64_be buf 25) in
  let polymarket_ask_price = Int64.float_of_bits (Bytes.get_int64_be buf 33) in
  
  (mode, { Ast.microprice; binance_imbalance; ai_prediction_up; ai_prediction_down; polymarket_ask_price })

let encode_action (action : Ast.trade_action) : char =
  match action with
  | Ast.Hold -> '\x00'
  | Ast.Buy  -> '\x01'
  | Ast.Sell -> '\x02'

let string_of_action (action : Ast.trade_action) : string =
  match action with
  | Ast.Hold -> "HOLD"
  | Ast.Buy  -> "BUY"
  | Ast.Sell -> "SELL"

let string_of_market_state (s : Ast.market_state) : string =
  Printf.sprintf "microprice=$%.2f | imbalance=%.4f | ai_up=%.4f | ai_down=%.4f | poly_ask=%.4f"
    s.microprice s.binance_imbalance s.ai_prediction_up s.ai_prediction_down s.polymarket_ask_price
