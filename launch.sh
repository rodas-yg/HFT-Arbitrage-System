#!/usr/bin/env bash
# Global Sentiment Router: One-Click Launcher
#
# Builds and starts the full pipeline in the correct order:
#   1. OCaml Strategy Engine (UDP 8890)
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

echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║     Global Sentiment Router - Launcher   ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════╝${RESET}"

echo "Select Execution Mode:"
echo "  1) BINANCE_ONLY"
echo "  2) PREDICTION_MARKET_ARBITRAGE"
read -p "Enter 1 or 2: " mode_choice

if [[ "$mode_choice" == "1" ]]; then
    echo '{"execution_mode": "BINANCE"}' > "$ROOT_DIR/config.json"
    echo -e "${GREEN}Mode set to BINANCE_ONLY${RESET}"
elif [[ "$mode_choice" == "2" ]]; then
    echo '{"execution_mode": "ARBITRAGE"}' > "$ROOT_DIR/config.json"
    echo -e "${GREEN}Mode set to PREDICTION_MARKET_ARBITRAGE${RESET}"
else
    echo -e "${RED}Invalid choice. Defaulting to BINANCE_ONLY${RESET}"
    echo '{"execution_mode": "BINANCE"}' > "$ROOT_DIR/config.json"
fi
echo ""

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
    sleep 1
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    echo -e "${GREEN}All components stopped.${RESET}"
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

prefix_output() {
    local color="$1"
    local tag="$2"
    while IFS= read -r line; do
        echo -e "${color}[${tag}]${RESET} ${line}"
    done
}

# Build Phase
if [[ "${1:-}" != "--skip-build" ]]; then
    echo -e "${MAGENTA}[build]${RESET} Compiling OCaml strategy engine..."
    (cd "$ROOT_DIR/strats" && eval "$(opam env)" && dune build 2>&1) | prefix_output "$MAGENTA" "build"
    echo -e "${MAGENTA}[build]${RESET} ✓ OCaml built"

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
echo -e "${BOLD}${GREEN}║          Global Sentiment Router — Starting Pipeline         ║${RESET}"
echo -e "${BOLD}${GREEN}╠══════════════════════════════════════════════════════════════╣${RESET}"
echo -e "${BOLD}${GREEN}║  ${MAGENTA}OCaml${GREEN}   Strategy Engine    → UDP 8890                       ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${BLUE}Java${GREEN}    Execution Engine   → UDP 8888 (market) 8889 (AI)    ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${YELLOW}Python${GREEN}  LSTM Inference     → sends to UDP 8889              ║${RESET}"
echo -e "${BOLD}${GREEN}║  ${CYAN}Python${GREEN}  Market Ingester    → sends to UDP 8888              ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"
echo ""

if [[ "$mode_choice" == "2" ]]; then
    # Prompt the user BEFORE starting any background noise
    PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/ml_predictor.py" --prompt-only
fi


echo -e "${MAGENTA}[ocaml]${RESET} Starting strategy engine..."
(cd "$ROOT_DIR/strats" && eval "$(opam env)" && exec dune exec bin/strategy_server.exe 2>&1) \
    | prefix_output "$MAGENTA" "ocaml" &
PIDS+=($!)
sleep 1

echo -e "${BLUE}[java]${RESET}  Starting execution engine..."
java -cp "$ROOT_DIR/execution/target/classes" com.router.network.Receiver 2>&1 \
    | prefix_output "$BLUE" "java" &
PIDS+=($!)
sleep 1

echo -e "${CYAN}[feed]${RESET}  Starting market data ingester..."
if [ -f "$ROOT_DIR/ingester/main.py" ]; then
    PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/main.py" 2>&1 \
        | prefix_output "$CYAN" "feed" &
    PIDS+=($!)
else
    echo -e "${CYAN}[feed]${RESET}  ingester/main.py not found, skipping."
fi

echo -e "${YELLOW}[ml]${RESET}    Starting LSTM inference engine..."
if [[ "$mode_choice" == "2" ]]; then
    PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/ml_predictor.py" --run-only 2>&1 \
        | prefix_output "$YELLOW" "ml" &
    PIDS+=($!)
else
    PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/ingester/ml.py" 2>&1 \
        | prefix_output "$YELLOW" "ml" &
    PIDS+=($!)
fi

echo ""
echo -e "${BOLD}${GREEN}All components launched. Press Ctrl+C to stop.${RESET}"
echo -e "${BOLD}────────────────────────────────────────────────────────────────${RESET}"
echo ""

wait
