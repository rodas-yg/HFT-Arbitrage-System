import { useEffect, useState, useRef } from "react";
import { Activity, TrendingUp, TrendingDown } from "lucide-react";

interface TelemetryPanelProps {
    selectedMarket: string | null;
}

interface LogEntry {
    timestamp: string;
    message: string;
    type: "info" | "success" | "warning";
}

export function TelemetryPanel({ selectedMarket }: TelemetryPanelProps) {
    const [probUp, setProbUp] = useState(87.4);
    const [probDown, setProbDown] = useState(12.6);
    const [obi, setObi] = useState(0.342);
    const [momentum, setMomentum] = useState(1.24);
    const [logs, setLogs] = useState<LogEntry[]>([
        { timestamp: "14:02:01.004", message: "AI Confidence 89% -> Executing POLY_BUY $50 @ $0.45", type: "success" },
        { timestamp: "14:01:45.231", message: "Market scanner detected high liquidity opportunity", type: "info" },
        { timestamp: "14:01:32.108", message: "PyTorch model inference complete: 234ms", type: "info" },
        { timestamp: "14:01:15.892", message: "Binance orderbook delta: +$42.3k BUY pressure", type: "info" },
    ]);
    const logsEndRef = useRef<HTMLDivElement>(null);

    // Connect to Live WebSocket Bridge
    useEffect(() => {
        const ws = new WebSocket("ws://localhost:8765");

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "telemetry") {
                    setProbUp(Number(data.probUp.toFixed(1)));
                    setProbDown(Number(data.probDown.toFixed(1)));
                    setObi(Number(data.obi.toFixed(3)));
                    setMomentum(Number(data.momentum.toFixed(2)));
                } else if (data.type === "log") {
                    setLogs((prev) => [...prev.slice(-49), {
                        timestamp: data.timestamp,
                        message: data.message,
                        type: data.logType
                    }]);
                }
            } catch (err) {
                console.error("Failed to parse websocket message", err);
            }
        };

        ws.onopen = () => {
            setLogs((prev) => [...prev, {
                timestamp: new Date().toISOString().split('T')[1].slice(0, 12),
                message: "Connected to Engine Telemetry Stream (ws://localhost:8765)",
                type: "success"
            }]);
        };

        ws.onclose = () => {
            setLogs((prev) => [...prev, {
                timestamp: new Date().toISOString().split('T')[1].slice(0, 12),
                message: "Disconnected from Engine",
                type: "warning"
            }]);
        };

        return () => ws.close();
    }, []);

    // Auto-scroll to bottom
    useEffect(() => {
        logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [logs]);

    return (
        <div className="h-full flex flex-col">
            {/* Header */}
            <div className="border-b border-[#2A2A2A] px-4 py-3">
                <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-gray-500" strokeWidth={1.5} />
                    <h2 className="text-sm text-gray-300 uppercase tracking-wider font-mono">Live Telemetry</h2>
                </div>
            </div>

            {/* AI Gauges */}
            <div className="border-b border-[#2A2A2A] p-4 space-y-3">
                <div className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-3">
                    AI Prediction Engine
                </div>

                {/* PROB_UP */}
                <div className="bg-[#121212] border border-[#2A2A2A] p-3">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <TrendingUp className="w-3.5 h-3.5 text-[#22C55E]" strokeWidth={2} />
                            <span className="text-xs font-mono text-gray-500">PROB_UP</span>
                        </div>
                        <span className="text-2xl font-mono text-[#22C55E]">{probUp.toFixed(1)}%</span>
                    </div>
                    <div className="h-1 bg-[#0A0A0A] overflow-hidden">
                        <div
                            className="h-full bg-[#22C55E] transition-all duration-500"
                            style={{ width: `${probUp}%` }}
                        />
                    </div>
                </div>

                {/* PROB_DOWN */}
                <div className="bg-[#121212] border border-[#2A2A2A] p-3">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                            <TrendingDown className="w-3.5 h-3.5 text-[#EF4444]" strokeWidth={2} />
                            <span className="text-xs font-mono text-gray-500">PROB_DOWN</span>
                        </div>
                        <span className="text-2xl font-mono text-[#EF4444]">{probDown.toFixed(1)}%</span>
                    </div>
                    <div className="h-1 bg-[#0A0A0A] overflow-hidden">
                        <div
                            className="h-full bg-[#EF4444] transition-all duration-500"
                            style={{ width: `${probDown}%` }}
                        />
                    </div>
                </div>
            </div>

            {/* Market Physics */}
            <div className="border-b border-[#2A2A2A] p-4">
                <div className="text-xs text-gray-500 font-mono uppercase tracking-wider mb-3">
                    Market Physics
                </div>
                <div className="grid grid-cols-2 gap-2">
                    <div className="bg-[#121212] border border-[#2A2A2A] p-2.5">
                        <div className="text-xs text-gray-600 font-mono mb-1">Binance OBI</div>
                        <div className={`text-base font-mono ${obi > 0 ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>
                            {obi > 0 ? '+' : ''}{obi.toFixed(3)}
                        </div>
                    </div>
                    <div className="bg-[#121212] border border-[#2A2A2A] p-2.5">
                        <div className="text-xs text-gray-600 font-mono mb-1">μPrice Δ</div>
                        <div className={`text-base font-mono ${momentum > 0 ? 'text-[#22C55E]' : 'text-[#EF4444]'}`}>
                            {momentum > 0 ? '+' : ''}{momentum.toFixed(2)}
                        </div>
                    </div>
                </div>
            </div>

            {/* Execution Terminal */}
            <div className="flex-1 flex flex-col min-h-0">
                <div className="px-4 py-2.5 border-b border-[#2A2A2A]">
                    <div className="text-xs text-gray-500 font-mono uppercase tracking-wider">
                        Execution Terminal
                    </div>
                </div>
                <div className="flex-1 overflow-y-auto bg-[#000000] p-3 font-mono text-xs">
                    {logs.map((log, idx) => (
                        <div
                            key={idx}
                            className={`mb-1 ${log.type === 'success'
                                    ? 'text-[#22C55E]'
                                    : log.type === 'warning'
                                        ? 'text-[#F59E0B]'
                                        : 'text-gray-500'
                                }`}
                        >
                            <span className="text-gray-600">[{log.timestamp}]</span>{' '}
                            {log.message}
                        </div>
                    ))}
                    <div ref={logsEndRef} />
                </div>
            </div>
        </div>
    );
}
