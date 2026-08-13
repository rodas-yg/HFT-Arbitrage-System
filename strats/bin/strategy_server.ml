(** strategy_server.ml — UDP server for strategy evaluation
*)

open Strategy_engine

let port = 8890
let host = Unix.inet_addr_loopback

let () =
  let shutdown _ =
    Printf.printf "\n[OCaml] Shutting down strategy engine...\n%!";
    exit 0
  in
  Sys.set_signal Sys.sigint  (Sys.Signal_handle shutdown);
  Sys.set_signal Sys.sigterm (Sys.Signal_handle shutdown);

  let server_fd = Unix.socket Unix.PF_INET Unix.SOCK_DGRAM 0 in
  Unix.bind server_fd (Unix.ADDR_INET (host, port));

  Printf.printf " OCaml Strategy Engine v2.0 (UDP Mode)\n%!";
  Printf.printf " Listening on UDP 127.0.0.1:%d\n%!" port;
  Printf.printf " Protocol: 33B request -> 1B response\n%!";

  let request_buf = Bytes.create Wire.request_size in
  let response_buf = Bytes.create Wire.response_size in
  let eval_count = ref 0 in
  let last_trade_time = ref 0.0 in
  let cooldown_seconds = 30.0 in

  while true do
    let (bytes_read, client_addr) = Unix.recvfrom server_fd request_buf 0 Wire.request_size [] in
    if bytes_read = Wire.request_size then (
      let (mode, state) = Wire.decode_market_state request_buf in
      
      let pipeline = if mode = 0 then Strategies.binance_pipeline else Strategies.leadlag_pipeline in
      let raw_action = Strategies.eval_cascade state pipeline in

      let action =
        if raw_action <> Strategy_engine.Ast.Hold then
          let now = Unix.gettimeofday () in
          if now -. !last_trade_time >= cooldown_seconds then begin
            last_trade_time := now;
            Printf.printf "[OCaml] 🔥 TRIGGER %s 🔥 | %s\n%!"
              (Wire.string_of_action raw_action)
              (Wire.string_of_market_state state);
            raw_action
          end else begin
            Printf.printf "[OCaml] ⏳ COOLDOWN SUPPRESSED %s\n%!" (Wire.string_of_action raw_action);
            Strategy_engine.Ast.Hold
          end
        else
          Strategy_engine.Ast.Hold
      in

      Bytes.set response_buf 0 (Wire.encode_action action);
      
      let _ = Unix.sendto server_fd response_buf 0 Wire.response_size [] client_addr in

      incr eval_count;
      if !eval_count mod 100 = 0 then
        Printf.printf "[OCaml] #%d | MODE: %d | %s | -> %s\n%!"
          !eval_count
          mode
          (Wire.string_of_market_state state)
          (Wire.string_of_action action)
    )
  done
