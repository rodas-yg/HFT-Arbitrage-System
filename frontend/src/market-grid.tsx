import { BarChart3, Target, Clock } from "lucide-react";
import { useEffect, useState } from "react";

interface Market {
    idx: number;
    question: string;
    token_id: string;
    expiry: number;
    time_to_expiry: number;
    time_remaining_str: string;
}

interface MarketGridProps {
    selectedMarket: string | null;
    onSelectMarket: (id: string) => void;
}

export function MarketGrid({ selectedMarket, onSelectMarket }: MarketGridProps) {
    const [markets, setMarkets] = useState<Market[]>([]);
    const [ws, setWs] = useState<WebSocket | null>(null);
    const [lockedMarket, setLockedMarket] = useState<string | null>(null);

    useEffect(() => {
        const websocket = new WebSocket("ws://localhost:8765");
        setWs(websocket);
        
        websocket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "markets") {
                    setMarkets(data.markets);
                }
                if (data.type === "market_selected") {
                    setLockedMarket(data.token_id);
                }
            } catch (err) {
                console.error("Failed to parse websocket message", err);
            }
        };

        return () => websocket.close();
    }, []);

    const handleSelect = (market: Market) => {
        if (lockedMarket) return; // Already locked onto a market, engine is running
        onSelectMarket(market.token_id);
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "select_market", idx: market.idx }));
        }
        setLockedMarket(market.token_id);
    };

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="border-b border-[#2A2A2A] px-4 py-3">
                <div className="flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                    <h2 className="text-sm text-gray-300 uppercase tracking-wider font-mono">
                        Polymarket BTC Bet Selector
                    </h2>
                    <span className="ml-auto text-xs font-mono text-gray-600">
                        {markets.length} Active BTC Markets
                    </span>
                </div>
                {lockedMarket && (
                    <div className="mt-2 flex items-center gap-2">
                        <Target className="w-3.5 h-3.5 text-green-500" />
                        <span className="text-xs font-mono text-green-400">
                            LOCKED — Engine running until expiry
                        </span>
                    </div>
                )}
            </div>

            {/* Table */}
            <div className="flex-1 overflow-auto">
                <table className="w-full">
                    <thead className="sticky top-0 bg-[#0A0A0A] border-b border-[#2A2A2A]">
                        <tr>
                            <th className="text-left px-4 py-2.5 text-xs font-mono text-gray-500 uppercase tracking-wider w-8">
                                #
                            </th>
                            <th className="text-left px-4 py-2.5 text-xs font-mono text-gray-500 uppercase tracking-wider">
                                BTC Market Question
                            </th>
                            <th className="text-right px-4 py-2.5 text-xs font-mono text-gray-500 uppercase tracking-wider">
                                Time to Expiry
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {markets.map((market) => (
                            <tr
                                key={market.token_id}
                                onClick={() => handleSelect(market)}
                                className={`border-b border-[#1A1A1A] transition-colors ${
                                    lockedMarket === market.token_id
                                        ? "bg-green-950/30 border-green-900/40"
                                        : lockedMarket
                                        ? "opacity-40 cursor-not-allowed"
                                        : selectedMarket === market.token_id
                                        ? "bg-[#1A1A1A] border-[#2A2A2A]"
                                        : "hover:bg-[#121212] cursor-pointer"
                                }`}
                            >
                                <td className="px-4 py-3 text-xs font-mono text-gray-600">
                                    [{market.idx}]
                                </td>
                                <td className="px-4 py-3 text-sm text-gray-300">
                                    <div className="flex items-center gap-2">
                                        {lockedMarket === market.token_id && (
                                            <Target className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                                        )}
                                        {market.question}
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-sm font-mono text-right">
                                    <div className="flex items-center justify-end gap-1.5">
                                        <Clock className="w-3 h-3 text-gray-600" />
                                        <span className={`${
                                            market.time_to_expiry < 3600
                                                ? "text-red-400"
                                                : market.time_to_expiry < 86400
                                                ? "text-yellow-400"
                                                : "text-gray-400"
                                        }`}>
                                            {market.time_remaining_str}
                                        </span>
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {markets.length === 0 && (
                    <div className="flex items-center justify-center h-full text-gray-600 font-mono text-sm">
                        Loading BTC markets from Polymarket...
                    </div>
                )}
            </div>
        </div>
    );
}
