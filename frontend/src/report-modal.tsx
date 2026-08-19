import ReactMarkdown from 'react-markdown';
import { X, CheckCircle2 } from 'lucide-react';

interface ReportModalProps {
    markdown: string;
    onClose: () => void;
}

export function ReportModal({ markdown, onClose }: ReportModalProps) {
    return (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center p-8 z-50 overflow-y-auto">
            <div className="bg-[#121212] border border-[#2A2A2A] w-full max-w-4xl shadow-2xl mt-auto mb-auto">
                {/* Header */}
                <div className="border-b border-[#2A2A2A] px-6 py-4 flex items-center justify-between sticky top-0 bg-[#121212] z-10">
                    <div className="flex items-center gap-3">
                        <CheckCircle2 className="w-6 h-6 text-green-500" strokeWidth={2} />
                        <div>
                            <h2 className="text-xl text-gray-100 uppercase tracking-wider font-mono font-bold">Paper Trade Execution Report</h2>
                            <p className="text-xs text-gray-500 mt-0.5 font-mono">Engine successfully executed and closed the position.</p>
                        </div>
                    </div>
                    <button 
                        onClick={onClose}
                        className="text-gray-500 hover:text-gray-300 transition-colors"
                    >
                        <X className="w-6 h-6" />
                    </button>
                </div>

                {/* Markdown Content */}
                <div className="p-8 font-mono text-sm text-gray-300 prose prose-invert max-w-none prose-table:border-collapse prose-th:border prose-th:border-[#2A2A2A] prose-th:bg-[#1A1A1A] prose-th:p-2 prose-td:border prose-td:border-[#2A2A2A] prose-td:p-2 prose-tr:border-[#2A2A2A] prose-h1:text-xl prose-h2:text-lg prose-h2:border-b prose-h2:border-[#2A2A2A] prose-h2:pb-2">
                    <ReactMarkdown>{markdown}</ReactMarkdown>
                </div>

                {/* Footer */}
                <div className="border-t border-[#2A2A2A] bg-[#0A0A0A] px-6 py-4 text-right">
                    <button 
                        onClick={onClose}
                        className="px-6 py-2 bg-white text-black font-mono uppercase text-sm tracking-wider hover:bg-gray-200 transition-colors font-bold"
                    >
                        Acknowledge & Close
                    </button>
                </div>
            </div>
        </div>
    );
}
