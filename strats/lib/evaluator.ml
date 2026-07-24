(** evaluator.ml — Recursive pattern-matching AST evaluator

    This module implements the core evaluation logic for the strategy engine.
    Given a [market_state] and an [expr] AST, it recursively pattern-matches
    through the tree to produce a [trade_action].

    Performance characteristics:
    - Time complexity: O(n) where n = number of AST nodes
    - Space complexity: O(d) stack frames where d = tree depth
    - Short-circuit evaluation on [And] and [Or] nodes
    - No heap allocation during evaluation (all values are unboxed floats/bools)
    - Target latency: < 1µs for trees of depth ≤ 10

*)

let resolve_field (state : Ast.market_state) (field : Ast.market_field) : float =
  match field with
  | Ast.Microprice    -> state.microprice
  | Ast.Imbalance     -> state.imbalance
  | Ast.AiConfidence  -> state.ai_confidence
  | Ast.KalshiAskPrice -> state.kalshi_ask_price

let compare_op (op : Ast.comparison) (lhs : float) (rhs : float) : bool =
  match op with
  | Ast.Gt  -> lhs > rhs
  | Ast.Lt  -> lhs < rhs
  | Ast.Gte -> lhs >= rhs
  | Ast.Lte -> lhs <= rhs
  | Ast.Eq  -> Float.equal lhs rhs

(** Evaluate a boolean predicate AST node recursively.

    Short-circuit semantics:
    - [And (a, b)]: if [a] is false, [b] is never evaluated
    - [Or (a, b)]:  if [a] is true,  [b] is never evaluated

    This matches OCaml's native [&&] and [||] operators which are
    guaranteed to short-circuit by the language specification.

    @param state  The current market snapshot from Java
    @param expr   The AST node to evaluate
    @return       [true] if the predicate holds, [false] otherwise *)
let rec eval (state : Ast.market_state) (expr : Ast.expr) : bool =
  match expr with
  | Ast.Compare (field, op, threshold) ->
    let value = resolve_field state field in
    compare_op op value threshold
  | Ast.And (lhs, rhs) ->
    eval state lhs && eval state rhs
  | Ast.Or (lhs, rhs) ->
    eval state lhs || eval state rhs
  | Ast.Not e ->
    not (eval state e)
  | Ast.IfThenElse (cond, _, _) ->
    (* When used as a boolean sub-expression, IfThenElse degrades to
       evaluating just its condition. This allows nesting strategies
       inside boolean combinators. *)
    eval state cond

(** Top-level entry point: evaluate a complete strategy AST to a [trade_action].

    This is the function called by the IPC server on every tick.
    For a well-formed strategy, the root node should be [IfThenElse].
    If the root is a bare predicate, we treat [true -> Buy, false -> Hold]
    as a sensible default.

    @param state  The current market snapshot (3 floats from Java)
    @param expr   The root of the strategy AST
    @return       [Buy], [Sell], or [Hold] *)
let eval_action (state : Ast.market_state) (expr : Ast.expr) : Ast.trade_action =
  match expr with
  | Ast.IfThenElse (cond, on_true, on_false) ->
    if eval state cond then on_true else on_false
  | _ ->
    if eval state expr then Ast.Buy else Ast.Hold

    