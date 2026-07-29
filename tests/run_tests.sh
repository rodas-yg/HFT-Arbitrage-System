#!/usr/bin/env bash
# Run the Java Execution Engine and OCaml Strategy Server in the background,
# then run the fake stream test to verify end-to-end data processing.

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Starting OCaml Strategy Server..."
(cd "$ROOT_DIR/strats" && eval "$(opam env)" && exec dune exec bin/strategy_server.exe) &
OCAML_PID=$!

sleep 1 # wait for OCaml to bind

echo "Starting Java Execution Engine..."
java -cp "$ROOT_DIR/execution/target/classes" com.router.network.Receiver &
JAVA_PID=$!

sleep 1 # wait for Java to bind

echo "Starting Fake Stream Injector..."
python3 "$ROOT_DIR/tests/fake_stream_test.py" &
INJECTOR_PID=$!

echo "Letting the stream run for 5 seconds..."
sleep 5

echo "Shutting down tests..."
kill $INJECTOR_PID
kill $JAVA_PID
kill $OCAML_PID

echo "Test complete!"
