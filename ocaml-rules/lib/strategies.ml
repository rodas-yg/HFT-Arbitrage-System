
open Ast

(** Aggressive Short

    Detects strong selling pressure at high prices with ML confirmation.

    :
      IF (Microprice > 64000.0)
         AND (Imbalance < -0.8)        — heavy sell-side pressure
         AND (AI_Confidence > 0.90)     — ML model is highly confident
      THEN Sell
      ELSE Hold

    Use case: shows when the order book shows exhaustion. *)
let aggressive_short : expr =
  IfThenElse (
    And (
      Compare (Microprice, Gt, 64000.0),
      And (
        Compare (Imbalance, Lt, ~-.0.8),
        Compare (AiConfidence, Gt, 0.90)
      )
    ),
    Sell,
    Hold
  )

(** Momentum Long}

    Detects strong buying pressure with ML confirmation. //not sure about this one tho, we should backtest this!!!!!!

    Logic:
      IF (Imbalance > 0.7)              — heavy buy-side pressure
         AND (AI_Confidence > 0.85)      — ML model is confident
      THEN Buy
      ELSE Hold

    Use case: Ride momentum when buyers dominate the book. *)
let momentum_long : expr =
  IfThenElse (
    And (
      Compare (Imbalance, Gt, 0.7),
      Compare (AiConfidence, Gt, 0.85)
    ),
    Buy,
    Hold
  )

(** Mean Reversion

    looks for extreme imbalance conditions likely to revert.

    :
      IF (Imbalance < -0.9)             — extreme selling (likely to bounce)
         AND (Microprice < 60000.0)      — price has already dropped
      THEN Buy                           — contrarian entry
      ELSE IF (Imbalance > 0.9)          — extreme buying (likely to fade)
           AND (Microprice > 65000.0)    — price has already spiked
           THEN Sell                     — contrarian exit
           ELSE Hold

    Use case: Profit from order book imbalance extremes reverting to mean. *)
let mean_reversion : expr =
  IfThenElse (
    And (
      Compare (Imbalance, Lt, ~-.0.9),
      Compare (Microprice, Lt, 60000.0)
    ),
    Buy,
    (* Nested: check the sell-side reversion condition *)
    Hold  (* Outer else — will be overridden by composite *)
  )

let mean_reversion_sell : expr =
  IfThenElse (
    And (
      Compare (Imbalance, Gt, 0.9),
      Compare (Microprice, Gt, 65000.0)
    ),
    Sell,
    Hold
  )

(** Composite Strategy

    Chains multiple strategies with priority ordering:
    1. Check aggressive_short first (highest urgency — protect capital)
    2. Check momentum_long second  (opportunity — ride momentum)
    3. Default to Hold

    This demonstrates how [Or] nodes enable strategy composition.
    The evaluator short-circuits: if short fires, long is never checked. *)
let composite : expr =
  IfThenElse (
    (* Priority 1: Is the aggressive short triggered? *)
    And (
      Compare (Microprice, Gt, 64000.0),
      And (
        Compare (Imbalance, Lt, ~-.0.8),
        Compare (AiConfidence, Gt, 0.90)
      )
    ),
    Sell,
    (* Priority 2: momentum long is checked implicitly by choosing Buy
       only when the full composite passes. For true multi-strategy
       cascading, use the [eval_cascade] approach below. *)
    Hold
  ) 

(** Cascade Evaluator

    Evaluate a list of strategies in priority order.
    Returns the first non-Hold action, or Hold if all strategies pass.

    This is more flexible than a single composite AST because each
    strategy is independently defined and can be hot-swapped.

    @param state       The current market snapshot
    @param strategies  Ordered list of strategy ASTs (highest priority first)
    return   s         The first non-Hold action, or Hold *)
let eval_cascade (state : market_state) (strategies : expr list) : trade_action =
  let rec loop = function
    | [] -> Hold
    | strategy :: rest ->
      let action = Evaluator.eval_action state strategy in
      match action with
      | Hold -> loop rest
      | _    -> action  (* First non-Hold wins *)
  in
  loop strategies

(** The default production strategy pipeline.
    Ordered by priority: protect capital first, then seek opportunity : *)
let default_pipeline : expr list = [
  aggressive_short;
  momentum_long;
  mean_reversion;
  mean_reversion_sell;
]
