#!/usr/bin/env bash
# Global Sentiment Router: One-Click Launcher
#
# Builds and starts the full pipeline in the correct order:
#   1. OCaml Strategy Engine (UDS /tmp/gsr_strategy.sock)
#   2. Java Execution Engine (UDP 8888 market, 8889 AI, 9000 telem)
#   3. Python LSTM Inference (→ UDP 8889)
#   4. Python Market Ingester (→ UDP 8888)
#
# Usage:
#   ./launch.sh              # Launch everything
#   ./launch.sh --skip-build # Skip compilation, just run
#
# Press Ctrl+C to gracefully shut down all components.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors for each component
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# Cleanup: kill all child processes on exit
PIDS=()

cleanup() {
    echo ""
    echo -e "${BOLD}${RED}╔══════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${RED}║      Shutting down all components...     ║${RESET}"
    echo -e "${BOLD}${RED}╚══════════════════════════════════════════╝${RESET}"
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    # Wait briefly, then force-kill stragglers
    sleep 1
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    # Clean up stale OCaml socket
    rm -f /tmp/gsr_strategy.sock
    echo -e "${GREEN}All components stopped.${RESET}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

# Helper: prefix each line with a colored tag
prefix_output() {
    local color="$1"
    local tag="$2"
    while IFS= read -r line; do
        echo -e "${color}[${tag}]${RESET} ${line}"
    done
}

# Build Phase

if [[ "${1:-}" != "--skip-build" ]]; then
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}${CYAN}║     Building all components...           ║${RESET}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"

    # Build OCaml
    echo -e "${MAGENTA}[build]${RESET} Compiling OCaml strategy engine..."
    (cd "$ROOT_DIR/strats" && eval "$(opam env)" && dune build 2>&1) | prefix_output "$MAGENTA" "build"
    echo -e "${MAGENTA}[build]${RESET} ✓ OCaml built"

    # Build Java
    echo -e "${MAGENTA}[build]${RESET} Compiling Java execution engine..."
    mkdir -p "$ROOT_DIR/execution/target/classes"
    javac -d "$ROOT_DIR/execution/target/classes" \
        "$ROOT_DIR/execution/src/main/java/com/router/engine/"*.java \
        "$ROOT_DIR/execution/src/main/java/com/router/network/"*.java 2>&1 \
        | prefix_output "$MAGENTA" "build"
    echo -e "${MAGENTA}[build]${RESET} ✓ Java built"

    echo ""
fi

# Launch Phase

echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║          Global Sentiment Router — Starting Pipeline        ║${RESET}"
echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}${GREEN}║  ${MAGENTA}OCaml${GREEN}   Strategy Engine    → UDS /tmp/gsr_strategy.sock    ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${BLUE}Java${GREEN}    Execution Engine   → UDP 8888 (market) 8889 (AI)  ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${YELLOW}Python${GREEN}  LSTM Inference     → sends to UDP 8889             ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${CYAN}Python${GREEN}  Market Ingester    → sends to UDP 8888             ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

# 1. OCaml Strategy Engine
echo -e "${MAGENTA}[ocaml]${RESET} Starting strategy engine..."
(cd "$ROOT_DIR/strats" && eval "$(opam env)" && exec dune exec bin/strategy_server.exe 2>&1) \
    | prefix_output "$MAGENTA" "ocaml" &
PIDS+=($!)
sleep 1  # Give OCaml time to bind the socket

# 2. Java Execution Engine
echo -e "${BLUE}[java]${RESET}  Starting execution engine..."
java -cp "$ROOT_DIR/execution/target/classes" com.router.network.Receiver 2>&1 \
    | prefix_output "$BLUE" "java" &
PIDS+=($!)
sleep 1  # Give Java time to bind UDP ports + connect to OCaml

# 3. Python ML Inference
echo -e "${YELLOW}[ml]${RESET}    Starting LSTM inference engine..."
PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/ml.py" 2>&1 \
    | prefix_output "$YELLOW" "ml" &
PIDS+=($!)

# 4. Python Market Data Ingester
echo -e "${CYAN}[feed]${RESET}  Starting market data ingester..."
PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/main.py" 2>&1 \
    | prefix_output "$CYAN" "feed" &
PIDS+=($!)

echo ""
echo -e "${BOLD}${GREEN}All 4 components launched. Press Ctrl+C to stop.${RESET}"
echo -e "${BOLD}────────────────────────────────────────────────────────────────${RESET}"
echo ""

# Wait forever (until Ctrl+C)
wait
