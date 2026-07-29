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

(** Lead-Lag Strategy

    IF (AiPredictionUp > 0.85) AND (PolymarketAskPrice < 0.50) THEN Buy
*)
let leadlag_strategy : expr =
  IfThenElse (
    And (
      Compare (AiPredictionUp, Gt, 0.85),
      Compare (PolymarketAskPrice, Lt, 0.50)
    ),
    Buy,
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
  leadlag_strategy;
]
