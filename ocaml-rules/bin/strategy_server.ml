(** //COME BACK TO ME!!!!!!!!!!

strategy_server.ml — Unix Domain Socket server for strategy evaluation

    This is the main entry point for the OCaml stuff.
    It binds to a UDS and serves strategy evaluation requests
    from the Java stuff.

    my plan:
      1. Java connects to the UDS
      2. Java sends 24 bytes: [microprice:f64be | imbalance: | ai_conf:tbd]
      3. OCaml evaluates the strategy AST, encodes the resul
      4. OCaml sends 1 byte: [0x00=Hold | 0x01=Buy | 0x02=Sell] back to java
      5. erepeat from step 2 (persistent connection)

// some things here are TBD

    Performance target: < 5µs round-trip per evaluation.
*)

open Strategy_engine

(** Path to the Unix Domain Socket file. 
    Cleaned up on startup if stale from a previous run. *)
let socket_path = "/tmp/gsr_strategy.sock"

(** Read exactly [n] bytes from a file descriptor.
    Loops to handle partial reads (unlikely on UDS but correct). *)
let read_exact (fd : Unix.file_descr) (n : int) : Bytes.t =
  let buf = Bytes.create n in
  let rec loop offset remaining =
    if remaining <= 0 then ()
    else
      let bytes_read = Unix.read fd buf offset remaining in
      if bytes_read = 0 then
        raise (Failure "Connection closed by peer")
      else
        loop (offset + bytes_read) (remaining - bytes_read)
  in
  loop 0 n;
  buf

(** Write exactly [n] bytes to a file descriptor. *)
let write_exact (fd : Unix.file_descr) (buf : Bytes.t) : unit =
  let len = Bytes.length buf in
  let rec loop offset remaining =
    if remaining <= 0 then ()
    else
      let bytes_written = Unix.write fd buf offset remaining in
      loop (offset + bytes_written) (remaining - bytes_written)
  in
  loop 0 len

(** Handle a single connected client.
    Runs in a tight loop reading requests and writing responses.
    The connection is persistent — Java keeps it open for the session. *)
let handle_client (client_fd : Unix.file_descr) : unit =
  Printf.printf "[OCaml] Client connected. Evaluating strategy pipeline...\n%!";
  let eval_count = ref 0 in
  let strategy_pipeline = Strategies.default_pipeline in
  (try
    while true do
      (* 1. Read 24 bytes: 3 × float64 big-endian *)
      let request_buf = read_exact client_fd Wire.request_size in
      let state = Wire.decode_market_state request_buf in

      (* 2. Evaluate the strategy cascade *)
      let action = Strategies.eval_cascade state strategy_pipeline in

      (* 3. Write 1 byte response *)
      let response = Bytes.create Wire.response_size in
      Bytes.set response 0 (Wire.encode_action action);
      write_exact client_fd response;

      (* 4. Periodic logging (every 100 evaluations) *)
      incr eval_count;
      if !eval_count mod 100 = 0 then
        Printf.printf "[OCaml] #%d | %s | -> %s\n%!"
          !eval_count
          (Wire.string_of_market_state state)
          (Wire.string_of_action action)
    done
  with
  | Failure msg ->
    Printf.printf "[OCaml] Client disconnected: %s\n%!" msg
  | Unix.Unix_error (err, fn, _) ->
    Printf.printf "[OCaml] Socket error in %s: %s\n%!" fn (Unix.error_message err)
  );
  Unix.close client_fd

(** Clean up stale socket file from a previous run. *)
let cleanup_socket () =
  if Sys.file_exists socket_path then (
    Printf.printf "[OCaml] Removing stale socket: %s\n%!" socket_path;
    Unix.unlink socket_path
  )

(** Main entry point.
    Sets up signal handlers, binds the UDS, and accepts connections. *)
let () =
  (* Clean up stale socket *)
  cleanup_socket ();

  (* Handle SIGINT/SIGTERM gracefully *)
  let shutdown _ =
    Printf.printf "\n[OCaml] Shutting down strategy engine...\n%!";
    cleanup_socket ();
    exit 0
  in
  Sys.set_signal Sys.sigint  (Sys.Signal_handle shutdown);
  Sys.set_signal Sys.sigterm (Sys.Signal_handle shutdown);

  (* Create and bind the Unix Domain Socket *)
  let server_fd = Unix.socket Unix.PF_UNIX Unix.SOCK_STREAM 0 in
  Unix.bind server_fd (Unix.ADDR_UNIX socket_path);
  Unix.listen server_fd 1;  (* Backlog of 1 — only Java connects *)

  Printf.printf " OCaml Strategy Engine v1.0\n%!";
  Printf.printf " Listening on: %s\n%!" socket_path;
  Printf.printf " Strategies loaded: %d\n%!" (List.length Strategies.default_pipeline);
  Printf.printf " Protocol: 24B request -> 1B response\n%!";

  (* Accept loop — handles one client at a time (single Java engine) *)
  while true do
    let (client_fd, _addr) = Unix.accept server_fd in
    handle_client client_fd
  done
