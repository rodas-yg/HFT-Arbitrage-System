import re

with open('retrainer.py', 'r') as f:
    content = f.read()

# 1. Imports
content = content.replace(
    'import pandas as pd',
    'import pandas as pd\nimport json\nimport urllib.request\nimport ssl\nimport certifi'
)

# 2. Add LeadLagLSTMBinary
binary_class = """
class LeadLagLSTMBinary(nn.Module):
    def __init__(self, input_dim=7, hidden_dim=128, num_layers=2, num_classes=2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_dim, hidden_size=hidden_dim,
            num_layers=num_layers, batch_first=True, dropout=0.2,
        )
        self.fc1 = nn.Linear(hidden_dim, 32)
        self.relu = nn.ReLU()
        self.classifier = nn.Linear(32, num_classes)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        final_thought = lstm_out[:, -1, :]
        x = self.relu(self.fc1(final_thought))
        return self.classifier(x)
"""
content = content.replace(
    '        return self.classifier(x)',
    '        return self.classifier(x)\n' + binary_class,
    1 # only the first occurrence (which is LeadLagLSTM)
)

# 3. fetch_market_resolution and load_and_fuse_data
fetch_logic = """
def fetch_market_resolution(ticker):
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    url = f"https://gamma-api.polymarket.com/events?slug={ticker}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode())
            if len(data) > 0:
                for m in data[0].get("markets", []):
                    resolution = m.get("resolution")
                    if resolution and resolution.lower() in ("yes", "1"):
                        return 1
                    elif resolution and resolution.lower() in ("no", "0"):
                        return 0
                    outcome = m.get("outcomePrices")
                    if outcome:
                        prices = json.loads(outcome) if isinstance(outcome, str) else outcome
                        if prices and float(prices[0]) == 1.0:
                            return 1
                        elif prices and float(prices[0]) == 0.0:
                            return 0
            return None
    except Exception as e:
        log.warning(f"Failed to fetch resolution for {ticker}: {e}")
        return None

def load_and_fuse_data(is_binary=False) -> pd.DataFrame | None:"""

content = content.replace(
    'def load_and_fuse_data() -> pd.DataFrame | None:',
    fetch_logic
)

old_label_logic = """    df_fused['future_poly_midprice'] = df_fused.groupby('ticker')['midprice'].shift(-FUTURE_WINDOW_ROWS)
    df_fused['poly_future_return'] = (
        (df_fused['future_poly_midprice'] - df_fused['midprice']) / df_fused['midprice']
    )

    def classify_target(ret):
        if pd.isna(ret):
            return np.nan
        if ret >= PRICE_MOVEMENT_THRESHOLD:
            return 2.0   
        elif ret <= -PRICE_MOVEMENT_THRESHOLD:
            return 0.0   
        else:
            return 1.0   

    df_fused['target_label'] = df_fused['poly_future_return'].apply(classify_target)
    df_fused = df_fused.dropna(subset=['target_label'])
    df_fused['target_label'] = df_fused['target_label'].astype(int)

    return df_fused"""

new_label_logic = """    if is_binary:
        tickers = df_fused['ticker'].unique()
        log.info(f"Fetching resolutions for {len(tickers)} markets...")
        resolution_map = {}
        for t in tickers:
            res = fetch_market_resolution(t)
            if res is not None:
                resolution_map[t] = res
            time.sleep(0.1)
        
        df_fused['target_label'] = df_fused['ticker'].map(resolution_map)
        df_fused = df_fused.dropna(subset=['target_label'])
        if len(df_fused) == 0:
            log.error("No resolved markets found. Aborting.")
            return None
        df_fused['target_label'] = df_fused['target_label'].astype(int)
    else:
        df_fused['future_poly_midprice'] = df_fused.groupby('ticker')['midprice'].shift(-FUTURE_WINDOW_ROWS)
        df_fused['poly_future_return'] = (
            (df_fused['future_poly_midprice'] - df_fused['midprice']) / df_fused['midprice']
        )
        def classify_target(ret):
            if pd.isna(ret): return np.nan
            if ret >= PRICE_MOVEMENT_THRESHOLD: return 2.0   
            elif ret <= -PRICE_MOVEMENT_THRESHOLD: return 0.0   
            else: return 1.0   
        df_fused['target_label'] = df_fused['poly_future_return'].apply(classify_target)
        df_fused = df_fused.dropna(subset=['target_label'])
        df_fused['target_label'] = df_fused['target_label'].astype(int)

    return df_fused"""

content = content.replace(old_label_logic, new_label_logic)


# 4. compute_class_weights
old_weights = """def compute_class_weights(labels: np.ndarray) -> torch.Tensor:
    \"\"\"Inverse-frequency class weighting to handle FLAT-class imbalance.\"\"\"
    classes, counts = np.unique(labels, return_counts=True)
    total = len(labels)
    weights = np.ones(3, dtype=np.float32)
    for cls, cnt in zip(classes, counts):
        if cnt > 0:
            weights[int(cls)] = total / (len(classes) * cnt)
    return torch.tensor(weights)"""

new_weights = """def compute_class_weights(labels: np.ndarray, is_binary=False) -> torch.Tensor:
    \"\"\"Inverse-frequency class weighting to handle FLAT-class imbalance.\"\"\"
    classes, counts = np.unique(labels, return_counts=True)
    total = len(labels)
    num_classes = 2 if is_binary else 3
    weights = np.ones(num_classes, dtype=np.float32)
    for cls, cnt in zip(classes, counts):
        if cnt > 0 and int(cls) < num_classes:
            weights[int(cls)] = total / (len(classes) * cnt)
    return torch.tensor(weights)"""

content = content.replace(old_weights, new_weights)


# 5. Modify main() to support --binary
content = content.replace(
    'parser.add_argument("--dry-run", action="store_true",',
    'parser.add_argument("--binary", action="store_true", help="Train binary resolution model")\n    parser.add_argument("--dry-run", action="store_true",'
)

content = content.replace(
    'df_fused = load_and_fuse_data()',
    'df_fused = load_and_fuse_data(is_binary=args.binary)'
)

content = content.replace(
    'class_weights = compute_class_weights(y_train).to(device)',
    'class_weights = compute_class_weights(y_train, is_binary=is_binary).to(device)'
)
# Wait, train() doesn't have is_binary. Let's pass it to train()
content = content.replace(
    'def train(model: nn.Module, device: torch.device,\n          X: np.ndarray, y: np.ndarray) -> dict:',
    'def train(model: nn.Module, device: torch.device,\n          X: np.ndarray, y: np.ndarray, is_binary: bool = False) -> dict:'
)

content = content.replace(
    'model = LeadLagLSTM().to(device)',
    'model = LeadLagLSTMBinary().to(device) if args.binary else LeadLagLSTM().to(device)'
)
content = content.replace(
    'metrics = train(model, device, X, y)',
    'metrics = train(model, device, X, y, is_binary=args.binary)'
)
content = content.replace(
    'if not os.path.exists(MODEL_PATH):',
    'model_path = "leadlag_binary.pt" if args.binary else MODEL_PATH\n        if not os.path.exists(model_path):'
)
content = content.replace(
    'model.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))',
    'model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))'
)
content = content.replace(
    'log.info(f"  Loaded existing weights from \'{MODEL_PATH}\'")',
    'log.info(f"  Loaded existing weights from \'{model_path}\'")'
)
content = content.replace(
    'os.replace(STAGING_PATH, MODEL_PATH)',
    'os.replace(STAGING_PATH, model_path)'
)
content = content.replace(
    'log.info(f"  Atomically replaced \'{MODEL_PATH}\' with retrained weights")',
    'log.info(f"  Atomically replaced \'{model_path}\' with retrained weights")'
)

with open('retrainer.py', 'w') as f:
    f.write(content)

