val resolve_field : Ast.market_state -> Ast.market_field -> float
val compare_op : Ast.comparison -> float -> float -> bool
val eval : Ast.market_state -> Ast.expr -> bool
val eval_action : Ast.market_state -> Ast.expr -> Ast.trade_action
