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

let bullish_state : Ast.market_state =
  { microprice = 63000.0; imbalance = 0.85; ai_confidence = 0.92; kalshi_ask_price = 0.6 }

let bearish_state : Ast.market_state =
  { microprice = 65000.0; imbalance = -0.85; ai_confidence = 0.95; kalshi_ask_price = 0.6 }

let neutral_state : Ast.market_state =
  { microprice = 62000.0; imbalance = 0.1; ai_confidence = 0.5; kalshi_ask_price = 0.6 }

let no_ai_state : Ast.market_state =
  { microprice = 65000.0; imbalance = -0.9; ai_confidence = 0.0; kalshi_ask_price = 0.6 }

let test_compare () =
  Printf.printf "\n[Compare nodes]\n%!";
  let expr_gt = Ast.Compare (Ast.Microprice, Ast.Gt, 64000.0) in
  assert_bool "microprice > 64000 (63000)" false (Evaluator.eval bullish_state expr_gt);
  assert_bool "microprice > 64000 (65000)" true (Evaluator.eval bearish_state expr_gt);

  let expr_lt = Ast.Compare (Ast.Imbalance, Ast.Lt, -0.8) in
  assert_bool "imbalance < -0.8 (0.85)" false (Evaluator.eval bullish_state expr_lt);
  assert_bool "imbalance < -0.8 (-0.85)" true (Evaluator.eval bearish_state expr_lt)

let test_boolean_combinators () =
  Printf.printf "\n[Boolean combinators]\n%!";
  let and_expr = Ast.And (
    Ast.Compare (Ast.Microprice, Ast.Gt, 64000.0),
    Ast.Compare (Ast.Imbalance, Ast.Lt, -0.8)
  ) in
  assert_bool "AND(mp>64k, imb<-0.8) bearish" true (Evaluator.eval bearish_state and_expr);
  assert_bool "AND(mp>64k, imb<-0.8) bullish" false (Evaluator.eval bullish_state and_expr);

  let or_expr = Ast.Or (
    Ast.Compare (Ast.Imbalance, Ast.Gt, 0.7),
    Ast.Compare (Ast.AiConfidence, Ast.Gt, 0.9)
  ) in
  assert_bool "OR(imb>0.7, ai>0.9) bullish" true (Evaluator.eval bullish_state or_expr);
  assert_bool "OR(imb>0.7, ai>0.9) neutral" false (Evaluator.eval neutral_state or_expr);

  let not_expr = Ast.Not (Ast.Compare (Ast.Imbalance, Ast.Gt, 0.0)) in
  assert_bool "NOT(imb>0) bearish" true (Evaluator.eval bearish_state not_expr);
  assert_bool "NOT(imb>0) bullish" false (Evaluator.eval bullish_state not_expr)

let test_strategies () =
  Printf.printf "\n[Strategy evaluation]\n%!";
  assert_action "aggressive_short on bearish"
    Ast.Sell (Evaluator.eval_action bearish_state Strategies.aggressive_short);
  assert_action "aggressive_short on bullish"
    Ast.Hold (Evaluator.eval_action bullish_state Strategies.aggressive_short);
  assert_action "aggressive_short on neutral"
    Ast.Hold (Evaluator.eval_action neutral_state Strategies.aggressive_short);
  assert_action "aggressive_short without AI"
    Ast.Hold (Evaluator.eval_action no_ai_state Strategies.aggressive_short);

  assert_action "momentum_long on bullish"
    Ast.Buy (Evaluator.eval_action bullish_state Strategies.momentum_long);
  assert_action "momentum_long on bearish"
    Ast.Hold (Evaluator.eval_action bearish_state Strategies.momentum_long);
  assert_action "momentum_long on neutral"
    Ast.Hold (Evaluator.eval_action neutral_state Strategies.momentum_long)

let test_cascade () =
  Printf.printf "\n[Strategy cascade]\n%!";
  assert_action "cascade on bearish (should Sell first)"
    Ast.Sell (Strategies.eval_cascade bearish_state Strategies.default_pipeline);
  assert_action "cascade on bullish (should Buy)"
    Ast.Buy (Strategies.eval_cascade bullish_state Strategies.default_pipeline);
  assert_action "cascade on neutral (should Hold)"
    Ast.Hold (Strategies.eval_cascade neutral_state Strategies.default_pipeline);
  assert_action "cascade without AI (should Hold)"
    Ast.Hold (Strategies.eval_cascade no_ai_state Strategies.default_pipeline)

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
  let original = bearish_state in
  let buf = Bytes.create 24 in
  Bytes.set_int64_be buf 0  (Int64.bits_of_float original.microprice);
  Bytes.set_int64_be buf 8  (Int64.bits_of_float original.imbalance);
  Bytes.set_int64_be buf 16 (Int64.bits_of_float original.ai_confidence);
  let decoded = Wire.decode_market_state buf in
  assert_bool "market_state microprice roundtrip"
    true (Float.equal original.microprice decoded.microprice);
  assert_bool "market_state imbalance roundtrip"
    true (Float.equal original.imbalance decoded.imbalance);
  assert_bool "market_state ai_confidence roundtrip"
    true (Float.equal original.ai_confidence decoded.ai_confidence)

let benchmark_eval () =
  Printf.printf "\n[Benchmark]\n%!";
  let iterations = 1_000_000 in
  let state = bearish_state in
  let strategy = Strategies.aggressive_short in
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
  test_compare ();
  test_boolean_combinators ();
  test_strategies ();
  test_cascade ();
  test_wire_roundtrip ();
  benchmark_eval ();
  Printf.printf "\n=== All tests passed ===\n%!"