(** test_evaluator.ml — Unit tests for the strategy engine evaluator *)

open Strategy_engine

(* Test helpers *)
let pass name = Printf.printf "  ✓ %s\n%!" name
let fail name expected got =
  Printf.printf "  ✗ %s — expected %s, got %s\n%!" name expected got;
  exit 1

let assert_action name expected actual =
  if expected = actual then pass name
  else fail name (Wire.string_of_action expected) (Wire.string_of_action actual)

let assert_bool name expected actual =
  if expected = actual then pass name
  else fail name (string_of_bool expected) (string_of_bool actual)

let bullish_binance_state : Ast.market_state =
  { microprice = 63000.0; binance_imbalance = -0.9; ai_prediction_up = 0.90; ai_prediction_down = 0.05; polymarket_ask_price = 0.6 }

let bearish_binance_state : Ast.market_state =
  { microprice = 65000.0; binance_imbalance = -0.7; ai_prediction_up = 0.80; ai_prediction_down = 0.15; polymarket_ask_price = 0.6 }

let arbitrage_state : Ast.market_state =
  { microprice = 65000.0; binance_imbalance = 0.0; ai_prediction_up = 0.90; ai_prediction_down = 0.05; polymarket_ask_price = 0.40 }

let test_strategies () =
  Printf.printf "\n[Strategy evaluation]\n%!";
  assert_action "binance_strategy on bullish (imbalance < -0.8 and ai_up > 0.85)"
    Ast.Buy (Evaluator.eval_action bullish_binance_state Strategies.binance_strategy);
  assert_action "binance_strategy on bearish"
    Ast.Hold (Evaluator.eval_action bearish_binance_state Strategies.binance_strategy);

  assert_action "leadlag_pipeline on arbitrage (ai_up > 0.60)"
    Ast.Buy (Strategies.eval_cascade arbitrage_state Strategies.leadlag_pipeline);
  assert_action "leadlag_pipeline on non-arbitrage"
    Ast.Hold (Strategies.eval_cascade bullish_binance_state Strategies.leadlag_pipeline)

let test_wire_roundtrip () =
  Printf.printf "\n[Wire protocol round-trip]\n%!";
  let actions = [Ast.Hold; Ast.Buy; Ast.Sell] in
  List.iter (fun action ->
    let encoded = Wire.encode_action action in
    let byte_val = Char.code encoded in
    let decoded = match byte_val with
      | 0 -> Ast.Hold | 1 -> Ast.Buy | 2 -> Ast.Sell
      | _ -> failwith "bad byte"
    in
    assert_action (Printf.sprintf "roundtrip %s" (Wire.string_of_action action))
      action decoded
  ) actions;

  (* Test market_state encode/decode *)
  let original = bullish_binance_state in
  let buf = Bytes.create 41 in
  Bytes.set buf 0 (char_of_int 0); (* mode 0 *)
  Bytes.set_int64_be buf 1  (Int64.bits_of_float original.microprice);
  Bytes.set_int64_be buf 9  (Int64.bits_of_float original.binance_imbalance);
  Bytes.set_int64_be buf 17 (Int64.bits_of_float original.ai_prediction_up);
  Bytes.set_int64_be buf 25 (Int64.bits_of_float original.ai_prediction_down);
  Bytes.set_int64_be buf 33 (Int64.bits_of_float original.polymarket_ask_price);
  
  let (mode, decoded) = Wire.decode_market_state buf in
  assert_bool "market_state mode roundtrip"
    true (mode = 0);
  assert_bool "market_state microprice roundtrip"
    true (Float.equal original.microprice decoded.microprice);
  assert_bool "market_state imbalance roundtrip"
    true (Float.equal original.binance_imbalance decoded.binance_imbalance);
  assert_bool "market_state ai_up roundtrip"
    true (Float.equal original.ai_prediction_up decoded.ai_prediction_up);
  assert_bool "market_state ai_down roundtrip"
    true (Float.equal original.ai_prediction_down decoded.ai_prediction_down);
  assert_bool "market_state poly_ask roundtrip"
    true (Float.equal original.polymarket_ask_price decoded.polymarket_ask_price)

let benchmark_eval () =
  Printf.printf "\n[Benchmark]\n%!";
  let iterations = 1_000_000 in
  let state = bullish_binance_state in
  let strategy = Strategies.binance_strategy in
  let t0 = Unix.gettimeofday () in
  for _ = 1 to iterations do
    ignore (Evaluator.eval_action state strategy)
  done;
  let elapsed = Unix.gettimeofday () -. t0 in
  let ns_per_eval = (elapsed *. 1e9) /. (float_of_int iterations) in
  Printf.printf "  %d evaluations in %.4fs = %.1f ns/eval\n%!" iterations elapsed ns_per_eval;
  if ns_per_eval > 1000.0 then (
    Printf.printf "  ✗ FAIL: eval took > 1µs (%.0f ns)\n%!" ns_per_eval;
    exit 1
  ) else
    Printf.printf "  ✓ PASS: eval < 1µs (%.0f ns)\n%!" ns_per_eval

let () =
  Printf.printf "=== OCaml Strategy Engine Test Suite ===\n%!";
  test_strategies ();
  test_wire_roundtrip ();
  benchmark_eval ();
  Printf.printf "\n=== All tests passed ===\n%!"