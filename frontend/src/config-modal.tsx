import { useState } from "react";
import { Lock } from "lucide-react";

interface ConfigModalProps {
    onSave: () => void;
}

export function ConfigModal({ onSave }: ConfigModalProps) {
    const [binanceApiKey, setBinanceApiKey] = useState("");
    const [binanceApiSecret, setBinanceApiSecret] = useState("");
    const [polymarketPrivateKey, setPolymarketPrivateKey] = useState("");

    const handleSave = () => {
        // In a real app, this would save to local JSON
        const config = {
            binanceApiKey,
            binanceApiSecret,
            polymarketPrivateKey,
            timestamp: new Date().toISOString(),
        };
        console.log("Saving config:", config);
        onSave();
    };

    const isValid = binanceApiKey && binanceApiSecret && polymarketPrivateKey;

    return (
        <div className="min-h-screen bg-[#0A0A0A] flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                {/* Modal Container */}
                <div className="bg-[#121212] border border-[#2A2A2A]">
                    {/* Header */}
                    <div className="border-b border-[#2A2A2A] px-6 py-4">
                        <div className="flex items-center gap-3">
                            <Lock className="w-5 h-5 text-gray-400" strokeWidth={1.5} />
                            <div>
                                <h2 className="text-lg text-gray-100">Environment Configuration</h2>
                                <p className="text-xs text-gray-500 mt-0.5 font-mono">Local initialization sequence</p>
                            </div>
                        </div>
                    </div>

                    {/* Form */}
                    <div className="p-6 space-y-5">
                        {/* Binance API Key */}
                        <div>
                            <label className="block text-xs text-gray-400 mb-2 font-mono uppercase tracking-wider">
                                Binance API Key
                            </label>
                            <input
                                type="text"
                                value={binanceApiKey}
                                onChange={(e) => setBinanceApiKey(e.target.value)}
                                className="w-full bg-[#0A0A0A] border border-[#2A2A2A] px-3 py-2.5 text-sm font-mono text-gray-200 focus:outline-none focus:border-[#3A3A3A] transition-colors"
                                placeholder="Enter Binance API key"
                            />
                        </div>

                        {/* Binance API Secret */}
                        <div>
                            <label className="block text-xs text-gray-400 mb-2 font-mono uppercase tracking-wider">
                                Binance API Secret
                            </label>
                            <input
                                type="password"
                                value={binanceApiSecret}
                                onChange={(e) => setBinanceApiSecret(e.target.value)}
                                className="w-full bg-[#0A0A0A] border border-[#2A2A2A] px-3 py-2.5 text-sm font-mono text-gray-200 focus:outline-none focus:border-[#3A3A3A] transition-colors"
                                placeholder="Enter Binance API secret"
                            />
                        </div>

                        {/* Polymarket Web3 Private Key */}
                        <div>
                            <label className="block text-xs text-gray-400 mb-2 font-mono uppercase tracking-wider">
                                Polymarket Web3 Private Key
                            </label>
                            <input
                                type="password"
                                value={polymarketPrivateKey}
                                onChange={(e) => setPolymarketPrivateKey(e.target.value)}
                                className="w-full bg-[#0A0A0A] border border-[#2A2A2A] px-3 py-2.5 text-sm font-mono text-gray-200 focus:outline-none focus:border-[#3A3A3A] transition-colors"
                                placeholder="Enter Polymarket private key"
                            />
                        </div>

                        {/* Info Notice */}
                        <div className="bg-[#0A0A0A] border border-[#2A2A2A] px-3 py-2.5">
                            <p className="text-xs text-gray-500 font-mono leading-relaxed">
                                Credentials are stored locally in config.json. No cloud transmission occurs.
                            </p>
                        </div>

                        {/* Save Button */}
                        <button
                            onClick={handleSave}
                            disabled={!isValid}
                            className={`w-full py-3 text-sm font-mono uppercase tracking-wider transition-colors ${isValid
                                    ? "bg-gray-100 text-[#0A0A0A] hover:bg-white cursor-pointer"
                                    : "bg-[#1A1A1A] text-gray-600 cursor-not-allowed"
                                }`}
                        >
                            Save to local config.json & Initialize Engine
                        </button>
                    </div>
                </div>

                {/* Footer */}
                <div className="mt-4 text-center">
                    <p className="text-xs text-gray-600 font-mono">HFT SaaS Platform v1.0.0</p>
                </div>
            </div>
        </div>
    );
}
