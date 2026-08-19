import { useState, useEffect } from "react";
import { Settings, Target, Clock } from "lucide-react";

interface SelectedMarketInfo {
    question: string;
    token_id: string;
    time_remaining: string;
}

export function StrategyPanel() {
    const [tradingMode, setTradingMode] = useState<"binance" | "polymarket">("polymarket");
    const [aiThreshold, setAiThreshold] = useState(85);
    const [maxCapital, setMaxCapital] = useState(50);
    const [selectedMarket, setSelectedMarket] = useState<SelectedMarketInfo | null>(null);

    useEffect(() => {
        const ws = new WebSocket("ws://localhost:8765");
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "market_selected") {
                    setSelectedMarket({
                        question: data.question,
                        token_id: data.token_id,
                        time_remaining: data.time_remaining,
                    });
                }
            } catch (err) { /* ignore */ }
        };
        return () => ws.close();
    }, []);

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="border-b border-[#2A2A2A] px-4 py-3">
                <div className="flex items-center gap-2">
                    <Settings className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                    <h2 className="text-sm text-gray-300 uppercase tracking-wider font-mono">Strategy Config</h2>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
                {/* Trading Mode */}
                <div>
                    <label className="block text-xs text-gray-500 mb-2.5 font-mono uppercase tracking-wider">
                        Trading Mode
                    </label>
                    <div className="grid grid-cols-1 gap-2">
                        <button
                            onClick={() => setTradingMode("binance")}
                            className={`px-3 py-2.5 text-xs font-mono border transition-colors text-left ${tradingMode === "binance"
                                    ? "bg-[#1A1A1A] border-gray-400 text-gray-100"
                                    : "bg-[#0A0A0A] border-[#2A2A2A] text-gray-500 hover:border-[#3A3A3A]"
                                }`}
                        >
                            BINANCE DIRECTIONAL
                        </button>
                        <button
                            onClick={() => setTradingMode("polymarket")}
                            className={`px-3 py-2.5 text-xs font-mono border transition-colors text-left ${tradingMode === "polymarket"
                                    ? "bg-[#1A1A1A] border-gray-400 text-gray-100"
                                    : "bg-[#0A0A0A] border-[#2A2A2A] text-gray-500 hover:border-[#3A3A3A]"
                                }`}
                        >
                            POLYMARKET LEAD-LAG
                        </button>
                    </div>
                </div>

                {/* AI Confidence Threshold */}
                <div>
                    <label className="block text-xs text-gray-500 mb-2.5 font-mono uppercase tracking-wider">
                        AI Confidence Execution Threshold
                    </label>
                    <div className="bg-[#121212] border border-[#2A2A2A] p-3">
                        <div className="flex items-baseline justify-between mb-2">
                            <span className="text-xs text-gray-500 font-mono">Threshold:</span>
                            <span className="text-lg font-mono text-gray-100">{aiThreshold}%</span>
                        </div>
                        <input
                            type="range"
                            min="50"
                            max="99"
                            value={aiThreshold}
                            onChange={(e) => setAiThreshold(Number(e.target.value))}
                            className="w-full h-1 bg-[#2A2A2A] appearance-none cursor-pointer slider"
                            style={{ accentColor: '#666' }}
                        />
                        <div className="flex justify-between mt-1.5">
                            <span className="text-xs text-gray-600 font-mono">50%</span>
                            <span className="text-xs text-gray-600 font-mono">99%</span>
                        </div>
                    </div>
                </div>

                {/* Max Capital Per Trade */}
                <div>
                    <label className="block text-xs text-gray-500 mb-2.5 font-mono uppercase tracking-wider">
                        Max Capital Per Trade
                    </label>
                    <div className="relative">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 font-mono">$</span>
                        <input
                            type="number"
                            value={maxCapital}
                            onChange={(e) => setMaxCapital(Number(e.target.value))}
                            className="w-full bg-[#121212] border border-[#2A2A2A] pl-7 pr-3 py-2.5 text-sm font-mono text-gray-100 focus:outline-none focus:border-[#3A3A3A] transition-colors"
                            min="1"
                            step="1"
                        />
                    </div>
                </div>

                {/* Risk Parameters */}
                <div className="bg-[#121212] border border-[#2A2A2A] p-3">
                    <div className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-2.5">
                        Risk Parameters
                    </div>
                    <div className="space-y-1.5 text-xs font-mono">
                        <div className="flex justify-between">
                            <span className="text-gray-600">Stop Loss:</span>
                            <span className="text-gray-400">-2.5%</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-600">Take Profit:</span>
                            <span className="text-gray-400">+5.0%</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-gray-600">Max Drawdown:</span>
                            <span className="text-gray-400">-15%</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Bottom: Active Market Status */}
            <div className="border-t border-[#2A2A2A] p-4">
                {selectedMarket ? (
                    <div className="space-y-3">
                        <div className="flex items-center gap-2">
                            <Target className="w-4 h-4 text-green-500" />
                            <span className="text-xs font-mono text-green-400 uppercase tracking-wider">Active Target</span>
                        </div>
                        <div className="bg-green-950/20 border border-green-900/30 p-3">
                            <p className="text-sm text-gray-200 leading-snug">{selectedMarket.question}</p>
                            <div className="flex items-center gap-1.5 mt-2">
                                <Clock className="w-3 h-3 text-gray-500" />
                                <span className="text-xs font-mono text-gray-400">
                                    Expires in {selectedMarket.time_remaining}
                                </span>
                            </div>
                            <p className="text-xs font-mono text-gray-600 mt-1 truncate">
                                {selectedMarket.token_id.slice(0, 20)}...
                            </p>
                        </div>
                        <div className="text-center">
                            <span className="inline-block px-3 py-1.5 text-xs font-mono bg-green-900/40 text-green-400 border border-green-800/50 uppercase tracking-wider">
                                Engine Running Until Expiry
                            </span>
                        </div>
                    </div>
                ) : (
                    <div className="text-center py-4">
                        <p className="text-xs font-mono text-gray-600 uppercase tracking-wider">
                            Select a BTC market to begin
                        </p>
                    </div>
                )}
            </div>
        </div>
    );
}
