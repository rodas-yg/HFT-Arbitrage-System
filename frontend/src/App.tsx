import { useState, useEffect } from "react";
import { StrategyPanel } from "./strategy-panel";
import { MarketGrid } from "./market-grid";
import { TelemetryPanel } from "./telemetry-panel";
import { ConfigModal } from "./config-modal";
import { TutorialPage } from "./tutorial-page";
import { ReportModal } from "./report-modal";
import { BookOpen } from "lucide-react";

export default function HFTCommandCenter() {
    const [isConfigured, setIsConfigured] = useState(false);
    const [selectedMarket, setSelectedMarket] = useState<string | null>(null);
    const [currentView, setCurrentView] = useState<"command" | "tutorial">("command");
    const [reportMarkdown, setReportMarkdown] = useState<string | null>(null);

    useEffect(() => {
        if (!isConfigured) return;
        const ws = new WebSocket("ws://localhost:8765");
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "report_ready") {
                    setReportMarkdown(data.markdown);
                }
            } catch (err) {
                // ignore
            }
        };
        return () => ws.close();
    }, [isConfigured]);

    const handleConfigSave = () => {
        setIsConfigured(true);
    };

    if (!isConfigured) {
        return <ConfigModal onSave={handleConfigSave} />;
    }

    if (currentView === "tutorial") {
        return <TutorialPage onBack={() => setCurrentView("command")} />;
    }

    return (
        <div className="min-h-screen bg-[#0A0A0A] text-gray-100 font-sans">
            <div className="h-screen flex flex-col">
                {/* Header */}
                <header className="border-b border-[#2A2A2A] px-6 py-3">
                    <div className="flex items-center justify-between">
                        <div>
                            <h1 className="text-xl text-gray-100 tracking-tight">HFT COMMAND CENTER</h1>
                            <p className="text-xs text-gray-500 mt-0.5 font-mono">Multi-Strategy Trading Engine</p>
                        </div>
                        <div className="flex items-center gap-4">
                            <button
                                onClick={() => setCurrentView("tutorial")}
                                className="flex items-center gap-2 px-3 py-1.5 bg-[#121212] border border-[#2A2A2A] text-gray-400 hover:border-gray-500 transition-colors text-xs font-mono uppercase tracking-wider"
                            >
                                <BookOpen className="w-3.5 h-3.5" strokeWidth={1.5} />
                                Documentation
                            </button>
                            <div className="text-xs font-mono text-gray-500">
                                <span className="text-gray-400">SYS:</span> ONLINE
                            </div>
                            <div className="text-xs font-mono text-gray-500">
                                {new Date().toLocaleTimeString('en-US', { hour12: false })}
                            </div>
                        </div>
                    </div>
                </header>

                {/* 3-Pane Layout */}
                <div className="flex-1 flex overflow-hidden">
                    {/* Left Panel: Strategy & Risk Configuration */}
                    <div className="w-80 border-r border-[#2A2A2A] bg-[#0A0A0A]">
                        <StrategyPanel />
                    </div>

                    {/* Middle Panel: Market Discovery Data-Grid */}
                    <div className="flex-1 bg-[#121212]">
                        <MarketGrid
                            selectedMarket={selectedMarket}
                            onSelectMarket={setSelectedMarket}
                        />
                    </div>

                    {/* Right Panel: Live Telemetry & Log */}
                    <div className="w-96 border-l border-[#2A2A2A] bg-[#0A0A0A]">
                        <TelemetryPanel selectedMarket={selectedMarket} />
                    </div>
                </div>
            </div>

            {reportMarkdown && (
                <ReportModal 
                    markdown={reportMarkdown} 
                    onClose={() => setReportMarkdown(null)} 
                />
            )}
        </div>
    );
}