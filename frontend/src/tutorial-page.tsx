import { Terminal, AlertCircle, Settings, BarChart3, Activity, Lock, TrendingUp, Shield } from "lucide-react";

interface TutorialPageProps {
    onBack: () => void;
}

export function TutorialPage({ onBack }: TutorialPageProps) {
    return (
        <div className="min-h-screen bg-[#0A0A0A] text-gray-100">
            {/* Header */}
            <header className="border-b border-[#2A2A2A] px-6 py-3">
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-xl text-gray-100 tracking-tight">SYSTEM DOCUMENTATION</h1>
                        <p className="text-xs text-gray-500 mt-0.5 font-mono">Operations Manual v1.0.0</p>
                    </div>
                    <button
                        onClick={onBack}
                        className="flex items-center gap-2 px-3 py-1.5 bg-[#121212] border border-[#2A2A2A] text-gray-400 hover:border-gray-500 transition-colors text-xs font-mono uppercase tracking-wider"
                    >
                        <Terminal className="w-3.5 h-3.5" strokeWidth={1.5} />
                        Return to Command Center
                    </button>
                </div>
            </header>

            {/* Content */}
            <div className="max-w-5xl mx-auto px-6 py-8">
                {/* Introduction */}
                <section className="mb-8">
                    <div className="border-l-2 border-gray-500 pl-4 mb-6">
                        <h2 className="text-lg text-gray-100 mb-2">OVERVIEW</h2>
                        <p className="text-sm text-gray-400 leading-relaxed">
                            This high-frequency trading platform enables automated execution across Binance spot markets and Polymarket prediction markets.
                            The system uses PyTorch-based AI models to analyze order flow, market microstructure, and sentiment data to generate directional predictions.
                        </p>
                    </div>
                </section>

                {/* Warning */}
                <div className="bg-[#121212] border border-[#EF4444] p-4 mb-8">
                    <div className="flex gap-3">
                        <AlertCircle className="w-5 h-5 text-[#EF4444] flex-shrink-0 mt-0.5" strokeWidth={1.5} />
                        <div>
                            <h3 className="text-sm text-[#EF4444] font-mono uppercase tracking-wider mb-1">Risk Disclosure</h3>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Algorithmic trading carries substantial financial risk. This software executes real trades with real capital.
                                Only use credentials for accounts you can afford to lose. Past performance does not guarantee future results.
                            </p>
                        </div>
                    </div>
                </div>

                {/* Section 1: Initial Configuration */}
                <section className="mb-8">
                    <div className="flex items-center gap-2 mb-4 pb-2 border-b border-[#2A2A2A]">
                        <Lock className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                        <h2 className="text-base text-gray-200 font-mono uppercase tracking-wider">01. Initial Configuration</h2>
                    </div>

                    <div className="space-y-4 ml-6">
                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Environment Setup</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                On first launch, you'll be prompted to configure your API credentials. All credentials are stored locally in <span className="font-mono text-gray-300">config.json</span> and never transmitted to external servers.
                            </p>
                            <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3 font-mono text-xs text-gray-500 space-y-1">
                                <div><span className="text-gray-600">Required:</span></div>
                                <div className="pl-4">• Binance API Key (read + trade permissions)</div>
                                <div className="pl-4">• Binance API Secret</div>
                                <div className="pl-4">• Polymarket Web3 Private Key (for CLOB access)</div>
                            </div>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Obtaining API Credentials</h3>
                            <div className="space-y-2 text-xs text-gray-400">
                                <div>
                                    <span className="text-gray-300 font-mono">Binance:</span> Navigate to Account → API Management → Create API
                                </div>
                                <div className="pl-4 text-gray-500">
                                    Enable: "Enable Reading" + "Enable Spot & Margin Trading"
                                </div>
                                <div className="mt-2">
                                    <span className="text-gray-300 font-mono">Polymarket:</span> Export private key from MetaMask or use dedicated trading wallet
                                </div>
                            </div>
                        </div>
                    </div>
                </section>

                {/* Section 2: Strategy Configuration */}
                <section className="mb-8">
                    <div className="flex items-center gap-2 mb-4 pb-2 border-b border-[#2A2A2A]">
                        <Settings className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                        <h2 className="text-base text-gray-200 font-mono uppercase tracking-wider">02. Strategy Configuration</h2>
                    </div>

                    <div className="space-y-4 ml-6">
                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Trading Mode Selection</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                The platform supports two distinct trading strategies:
                            </p>
                            <div className="space-y-3">
                                <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3">
                                    <div className="text-xs font-mono text-gray-300 mb-1">BINANCE DIRECTIONAL</div>
                                    <div className="text-xs text-gray-500 leading-relaxed">
                                        Pure price prediction on Binance spot markets. AI analyzes order book imbalance (OBI), microprice dynamics, and order flow toxicity to predict short-term price movements (1-30 minute horizon).
                                    </div>
                                </div>
                                <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3">
                                    <div className="text-xs font-mono text-gray-300 mb-1">POLYMARKET LEAD-LAG</div>
                                    <div className="text-xs text-gray-500 leading-relaxed">
                                        Exploits information asymmetry between Binance spot prices and Polymarket prediction markets. When BTC moves on Binance, the model predicts whether Polymarket contracts will update fast enough to create arbitrage opportunities.
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Risk Parameters</h3>
                            <div className="space-y-2 text-xs">
                                <div className="flex justify-between py-1.5 border-b border-[#1A1A1A]">
                                    <span className="text-gray-500 font-mono">AI Confidence Threshold</span>
                                    <span className="text-gray-400">Default: 85%</span>
                                </div>
                                <p className="text-gray-500 leading-relaxed">
                                    Minimum probability required for trade execution. Higher values = fewer but higher-conviction trades. Recommended range: 80-95%.
                                </p>

                                <div className="flex justify-between py-1.5 border-b border-[#1A1A1A] mt-3">
                                    <span className="text-gray-500 font-mono">Max Capital Per Trade</span>
                                    <span className="text-gray-400">Default: $50</span>
                                </div>
                                <p className="text-gray-500 leading-relaxed">
                                    Maximum position size per execution. Start small during testing. Professional traders typically risk 0.5-2% of capital per trade.
                                </p>
                            </div>
                        </div>
                    </div>
                </section>

                {/* Section 3: Market Selection */}
                <section className="mb-8">
                    <div className="flex items-center gap-2 mb-4 pb-2 border-b border-[#2A2A2A]">
                        <BarChart3 className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                        <h2 className="text-base text-gray-200 font-mono uppercase tracking-wider">03. Market Discovery</h2>
                    </div>

                    <div className="space-y-4 ml-6">
                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Market Grid Interface</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                The center panel displays all available markets (primarily Polymarket contracts for lead-lag strategy). Each row shows:
                            </p>
                            <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3 font-mono text-xs space-y-1.5">
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Target Ticker:</span>
                                    <span className="text-gray-500">Market question/description</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Time to Expiry:</span>
                                    <span className="text-gray-500">Hours/minutes until market closes</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Ask Price:</span>
                                    <span className="text-gray-500">Current best offer (0-1 probability)</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-600">Liquidity Vol:</span>
                                    <span className="text-gray-500">Total market depth</span>
                                </div>
                            </div>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Market Selection</h3>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Click any row to select it as the active target. The AI will focus predictions on the selected market.
                                Selected markets are highlighted in the grid and referenced in the telemetry panel.
                                Choose markets with high liquidity ({">"} $15k) and reasonable time to expiry ({">"} 30 min) for optimal execution.
                            </p>
                        </div>
                    </div>
                </section>

                {/* Section 4: Telemetry */}
                <section className="mb-8">
                    <div className="flex items-center gap-2 mb-4 pb-2 border-b border-[#2A2A2A]">
                        <Activity className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                        <h2 className="text-base text-gray-200 font-mono uppercase tracking-wider">04. Live Telemetry</h2>
                    </div>

                    <div className="space-y-4 ml-6">
                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">AI Prediction Gauges</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                Real-time PyTorch model outputs updated every 3-5 seconds:
                            </p>
                            <div className="space-y-2">
                                <div className="flex items-center gap-3">
                                    <TrendingUp className="w-4 h-4 text-[#22C55E]" strokeWidth={2} />
                                    <div className="flex-1">
                                        <div className="text-xs font-mono text-[#22C55E] mb-0.5">PROB_UP</div>
                                        <div className="text-xs text-gray-500">Probability of upward price movement / YES outcome</div>
                                    </div>
                                </div>
                                <div className="flex items-center gap-3">
                                    <TrendingUp className="w-4 h-4 text-[#EF4444] rotate-180" strokeWidth={2} />
                                    <div className="flex-1">
                                        <div className="text-xs font-mono text-[#EF4444] mb-0.5">PROB_DOWN</div>
                                        <div className="text-xs text-gray-500">Probability of downward price movement / NO outcome</div>
                                    </div>
                                </div>
                            </div>
                            <p className="text-xs text-gray-500 mt-3 leading-relaxed">
                                When PROB_UP exceeds your configured threshold, the engine executes a BUY. When PROB_DOWN exceeds threshold, engine executes a SELL.
                            </p>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Market Physics</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                Advanced microstructure indicators:
                            </p>
                            <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3 font-mono text-xs space-y-2">
                                <div>
                                    <span className="text-gray-300">Binance OBI</span>
                                    <span className="text-gray-600"> (Order Book Imbalance)</span>
                                </div>
                                <div className="text-gray-500 text-[11px] leading-relaxed pl-4">
                                    Measures buy vs. sell pressure in the limit order book. Positive = more bids, Negative = more asks. Range: -1.0 to +1.0
                                </div>

                                <div className="mt-2">
                                    <span className="text-gray-300">μPrice Δ</span>
                                    <span className="text-gray-600"> (Microprice Delta)</span>
                                </div>
                                <div className="text-gray-500 text-[11px] leading-relaxed pl-4">
                                    Volume-weighted midpoint momentum. Indicates smart money flow direction. Positive = bullish pressure building.
                                </div>
                            </div>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Execution Terminal</h3>
                            <p className="text-xs text-gray-400 leading-relaxed">
                                Terminal-style log displaying all system events: AI inference cycles, market scans, risk validations, and trade executions.
                                Each entry includes microsecond-precision timestamps. Green text indicates successful executions, yellow indicates warnings, gray is informational.
                            </p>
                        </div>
                    </div>
                </section>

                {/* Section 5: Execution */}
                <section className="mb-8">
                    <div className="flex items-center gap-2 mb-4 pb-2 border-b border-[#2A2A2A]">
                        <Shield className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                        <h2 className="text-base text-gray-200 font-mono uppercase tracking-wider">05. Engine Arming & Execution</h2>
                    </div>

                    <div className="space-y-4 ml-6">
                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">ARM ENGINE Protocol</h3>
                            <p className="text-xs text-gray-400 leading-relaxed mb-3">
                                The master control is located at the bottom of the Strategy Configuration panel.
                            </p>
                            <div className="space-y-2 text-xs text-gray-400">
                                <div className="flex items-start gap-2">
                                    <span className="text-gray-500 font-mono mt-0.5">1.</span>
                                    <span className="flex-1">Configure all parameters (trading mode, threshold, capital limit)</span>
                                </div>
                                <div className="flex items-start gap-2">
                                    <span className="text-gray-500 font-mono mt-0.5">2.</span>
                                    <span className="flex-1">Select target market from the discovery grid</span>
                                </div>
                                <div className="flex items-start gap-2">
                                    <span className="text-gray-500 font-mono mt-0.5">3.</span>
                                    <span className="flex-1">Monitor telemetry to verify AI predictions are updating</span>
                                </div>
                                <div className="flex items-start gap-2">
                                    <span className="text-gray-500 font-mono mt-0.5">4.</span>
                                    <span className="flex-1">Click "ARM ENGINE" to enable live trading</span>
                                </div>
                            </div>
                        </div>

                        <div className="bg-[#0A0A0A] border-2 border-[#EF4444] p-4">
                            <div className="flex gap-3">
                                <AlertCircle className="w-5 h-5 text-[#EF4444] flex-shrink-0 mt-0.5" strokeWidth={2} />
                                <div>
                                    <h3 className="text-sm text-[#EF4444] font-mono uppercase tracking-wider mb-2">Live Trading Active</h3>
                                    <p className="text-xs text-gray-400 leading-relaxed">
                                        When armed, the engine will automatically execute trades whenever AI confidence exceeds your threshold.
                                        Real orders are placed on live exchanges using real capital. Monitor the execution terminal closely.
                                        Click "DISARM ENGINE" to halt all automatic trading immediately.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className="bg-[#121212] border border-[#2A2A2A] p-4">
                            <h3 className="text-sm text-gray-300 mb-2 font-mono">Emergency Procedures</h3>
                            <div className="bg-[#0A0A0A] border border-[#2A2A2A] p-3 font-mono text-xs text-gray-500 space-y-1.5">
                                <div><span className="text-[#EF4444]">DISARM:</span> Click DISARM ENGINE to stop all execution</div>
                                <div><span className="text-[#F59E0B]">API REVOKE:</span> Disable API keys on exchange if system malfunction occurs</div>
                                <div><span className="text-gray-400">SUPPORT:</span> Contact engineering team via secure channel</div>
                            </div>
                        </div>
                    </div>
                </section>

                {/* Footer */}
                <div className="mt-12 pt-6 border-t border-[#2A2A2A]">
                    <p className="text-xs text-gray-600 font-mono text-center">
                        HFT Multi-Strategy SaaS Platform • v1.0.0 • For Authorized Use Only
                    </p>
                </div>
            </div>
        </div>
    );
}
