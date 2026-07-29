(** ast.ml — Algebraic Data Types

THIS SHI IS JUST VOCAB FOR THE REST OF THE PROJECT 
    
   defines the core type system for representing quantitative
    trading rules as a recursive Abstract Syntax Tree. 

    Design:
    - All types are simple sum/product types with no mutable state.
    - The [expr] type is intentionally recursive to support arbitrarily
      deep nesting of boolean logic
    - [IfThenElse] is the only node that produces a [trade_action];
      all other nodes produce boolean predicates.
*)


type market_state = {
  microprice           : float;  (** Volume-weighted midpoint *)
  binance_imbalance    : float;  (** Order Book Imbalance ∈ [-1.0, 1.0]. Positive = bullish *)
  ai_prediction_up     : float;  (** ML model prediction up prob *)
  ai_prediction_down   : float;  (** ML model prediction down prob *)
  polymarket_ask_price : float;  (** Polymarket "Yes" contract ask probability *)
}

type trade_action = 
  | Buy 
  | Sell 
  | Hold

type comparison = 
  | Gt   (** Greater than *)
  | Lt   (** Less than *)
  | Gte  (** Greater than or equal *)
  | Lte  (** Less than or equal *)
  | Eq   (** Equal (uses Float.equal for NaN safety) *)

(** Market data fields that can appear in predicates.
    These correspond 1:1 to fields in [market_state]*)
type market_field = 
  | Microprice 
  | BinanceImbalance 
  | AiPredictionUp
  | AiPredictionDown
  | PolymarketAskPrice

(** The AST node — a recursive algebraic data type.

    The tree structure supports:
    - Leaf nodes: [Compare] — numeric predicate on a single field
    - Interior nodes: [And], [Or], [Not] — boolean combinators
    - Root node: [IfThenElse] — maps a boolean predicate tree to a trade action


    {[
      IfThenElse (
        And (
          Compare (Microprice, Gt, 64000.0),
          Compare (Imbalance, Lt, -0.8)
        ),
        Sell,
        Hold
      )
    ]}
*)
type expr =
  | Compare    of market_field * comparison * float
  | And        of expr * expr
  | Or         of expr * expr
  | Not        of expr
  | IfThenElse of expr * trade_action * trade_action
