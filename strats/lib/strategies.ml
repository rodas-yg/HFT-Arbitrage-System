open Ast

(** Binance Strategy

    IF (BinanceImbalance < -0.8) AND (AiPredictionUp > 0.85) THEN Buy
*)
let binance_strategy : expr =
  IfThenElse (
    And (
      Compare (BinanceImbalance, Lt, ~-.0.8),
      Compare (AiPredictionUp, Gt, 0.85)
    ),
    Buy,
    Hold
  )

let leadlag_strategy_up : expr =
  IfThenElse (
    Compare (AiPredictionUp, Gt, 0.60),
    Buy,
    Hold
  )

let leadlag_strategy_down : expr =
  IfThenElse (
    Compare (AiPredictionDown, Gt, 0.60),
    Sell,
    Hold
  )

(** Cascade Evaluator
    Evaluate a list of strategies in priority order.
*)
let eval_cascade (state : market_state) (strategies : expr list) : trade_action =
  let rec loop = function
    | [] -> Hold
    | strategy :: rest ->
      let action = Evaluator.eval_action state strategy in
      match action with
      | Hold -> loop rest
      | _    -> action
  in
  loop strategies

let binance_pipeline : expr list = [
  binance_strategy;
]

let leadlag_pipeline : expr list = [
  leadlag_strategy_up;
  leadlag_strategy_down;
]
