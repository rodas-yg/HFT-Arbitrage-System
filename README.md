# Global Sentiment Router

Global Sentiment Router is a low-latency, multi-tier algorithmic routing and execution system designed for lead-lag arbitrage between high-liquidity cryptocurrency spot markets and prediction market contracts. The system processes high-frequency order book feeds, computes microstructural metrics, evaluates machine learning predictions, and executes rule-based strategies through a distributed polyglot pipeline.

## System Architecture

The pipeline consists of four primary subsystems communicating over local UDP sockets using fixed-size binary protocols:

1. Market Ingestion Layer (Python AsyncIO): Ingests Level 2 order book feeds from Binance and prediction market venues, extracts best bid/ask prices and sizes, and streams binary UDP packets.
2. High-Performance Execution Core (Java 21): Implements a lock-free single-producer single-consumer ring buffer with cache line padding to eliminate false sharing, ingests streaming AI inferences, computes microprice and order book imbalance, and dispatches state to the strategy engine.
3. Deterministic Strategy Engine (OCaml): Evaluates structured rule ASTs over binary market state packets in sub-microsecond round trips to return execution actions.
4. Deep Learning and Retraining Pipeline (PyTorch, Pandas, AsyncIO): Houses a sequence-based LSTM model for directional probability forecasting, streaming z-score feature normalizers, an as-of timestamp data fusion pipeline, and an offline/continuous model retrainer.
5. Paper Trading and Settlement Evaluator (Python): Tracks virtual fills triggered by high-confidence model predictions, monitors contract lifecycles until expiry, queries settlement endpoints, and produces performance ledgers.

## Network Protocol and IPC Specifications

Communication across processes uses binary serialization in network byte order (Big-Endian) over localhost UDP:

1. Market Data Stream:
Port: UDP 8888
Payload size: 40 bytes
Layout: timestamp_ns (int64), bid_price (float64), bid_quantity (float64), ask_price (float64), ask_quantity (float64)

2. AI Inference Stream (ML Predictor to Java Core):
Port: UDP 8889
Payload size: 16 bytes
Layout: prob_down (float64), prob_up (float64)

3. Prediction Market Data Stream (Ingester to Java Core):
Port: UDP 8891
Payload size: 24 bytes
Layout: timestamp_ns (int64), target_bid (float64), target_ask (float64)

4. Strategy Evaluation IPC (Java Core to OCaml Engine):
Port: UDP 8890
Request payload size: 41 bytes (1 byte execution mode flag followed by 5 float64 values: microprice, order book imbalance, probability up, probability down, target ask price)
Response payload size: 1 byte (0x00 for Hold, 0x01 for Buy, 0x02 for Sell)

5. Telemetry Broadcast:
Port: UDP 9000
Payload size: 33 bytes
Layout: timestamp_ns (int64), microprice (float64), imbalance (float64), ai_confidence (float64), action (uint8)

6. Trade Execution Evaluation Stream (ML Predictor to Reporter):
Port: UDP 8892
Payload size: 16 bytes
Layout: prob_down (float64), prob_up (float64)

## Core Technical Components

### 1. Java Core and Memory Layout

The Java engine processes incoming market data with zero allocation :

- Lock-Free RingBuffer: Operates over pre-allocated event objects with power-of-two sizing. Index masking using bitwise AND avoids modulo operations.
- False Sharing Prevention: The ring buffer sequence counters utilize dedicated padding classes allocating 56 bytes of dummy memory before and after the volatile sequence counter, forcing producer and consumer sequences into distinct 64-byte L1 CPU cache lines.
- Hardware Memory Fences: Sequence updates and reads use Java VarHandle acquire/release semantics (getAcquire and setRelease) to maintain memory visibility across CPU cores without heavy synchronization locks.
- Microstructure Math: Computes real-time microprice and Order Book Imbalance (OBI):
  Microprice = ((bid_qty * ask_price) + (ask_qty * bid_price)) / (bid_qty + ask_qty)
  Imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)

### 2. OCaml Strategy Engine

The strategy server is compiled via Dune into a native binary providing deterministic execution:

- Abstract Syntax Tree (AST): Strategies are encoded as functional expressions supporting boolean combinations, comparative operators, and market state field extractors.
- Cascade Evaluator: Evaluates ordered pipelines of conditional rules to generate discrete actions (Buy, Sell, Hold).
- Cooldown Throttling: Enforces configurable trade cooldown intervals to prevent rapid execution churn and manage risk.

### 3. Machine Learning and Feature Engineering

The inference engine predicts short-term directional movement using an LSTM neural network:

- Architecture: Two-layer LSTM backbone followed by fully connected layers with dropout and ReLU activations.
- Feature Vector:
  1. Prediction Market Order Book Imbalance
  2. Prediction Market Spread
  3. Time to Contract Expiry (seconds)
  4. Spot Market Order Book Imbalance
  5. Spot Microprice Momentum
  6. Spot Spread in Basis Points
  7. Spot to Prediction Market Volume Ratio
- Real-Time Normalization: Features are normalized using precomputed rolling means and standard deviations before tensor creation.
- Continuous Data Fusion: Merges asynchronous spot and prediction market tick files using backward timestamp matching (merge_asof) to align nanosecond events into labeled training sets.

### 4. Post-Market Paper Trading

The paper trading engine validates execution performance:

- Tracks entries on signals exceeding configurable confidence thresholds (e.g., probability greater than 0.60).
- Dynamically discovers active crypto binary prediction markets using venue APIs.
- Suspends settlement routines until contract expiration timestamps, retrieves final resolution states, and calculates realized PnL, win rates, and prediction confusion matrices.

## Execution Modes

1. Spot Mode: Trades spot order book momentum using order book imbalance and spot model inference.
2. Prediction Market Arbitrage Mode: Listens to cross-venue streams, evaluating lead-lag price discrepancies between fast spot movements and slower-moving binary prediction contracts.

## Project Status

Frontend integration and real-time dashboard connectivity are currently a work in progress.
