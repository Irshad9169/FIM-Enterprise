import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchReportDetail, exportReport } from "../api/dashboard";
import { Download, ArrowLeft } from "lucide-react";

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const navigate = useNavigate();

  const { data: report, isLoading, error } = useQuery({
    queryKey: ["report", reportId],
    queryFn: () => fetchReportDetail(reportId!),
    enabled: !!reportId,
  });

  const handleExport = async () => {
    try {
      const blob = await exportReport(reportId!);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `FIM-report-${reportId}.txt`;
      a.click();
    } catch (err) {
      alert('Failed to export report');
    }
  };

  if (isLoading) return <div className="text-center py-8">Loading report...</div>;
  if (error) return <div className="text-center py-8 text-red-400">Error loading report</div>;
  if (!report) return <div className="text-center py-8">Report not found</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate('/reports')}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800 rounded hover:bg-slate-700"
        >
          <ArrowLeft size={16} />
          Back to Reports
        </button>

        <button
          onClick={handleExport}
          className="flex items-center gap-2 px-4 py-2 bg-sky-600 rounded hover:bg-sky-700"
        >
          <Download size={16} />
          Export TXT
        </button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h1 className="text-2xl font-bold mb-4">
          FIM Report - {report.report_date}
        </h1>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-green-900/20 border border-green-700 rounded p-4">
            <div className="text-sm text-green-300">Added Files</div>
            <div className="text-3xl font-bold text-green-400 mt-1">
              {report.summary.added_files}
            </div>
          </div>

          <div className="bg-red-900/20 border border-red-700 rounded p-4">
            <div className="text-sm text-red-300">Removed Files</div>
            <div className="text-3xl font-bold text-red-400 mt-1">
              {report.summary.removed_files}
            </div>
          </div>

          <div className="bg-yellow-900/20 border border-yellow-700 rounded p-4">
            <div className="text-sm text-yellow-300">Changed Files</div>
            <div className="text-3xl font-bold text-yellow-400 mt-1">
              {report.summary.changed_files}
            </div>
          </div>
        </div>

        <div className="mb-6">
          <h3 className="font-semibold mb-2">Affected Agents ({report.agents?.length || 0})</h3>
          <div className="flex flex-wrap gap-2">
            {report.agents?.map((agent: string, idx: number) => (
              <span key={idx} className="px-3 py-1 bg-slate-800 rounded text-sm">
                {agent}
              </span>
            ))}
          </div>
        </div>

        {report.changes?.added?.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold text-green-400 mb-2">
              Added Files ({report.changes.added.length})
            </h3>
            <div className="bg-slate-950 rounded p-4 max-h-60 overflow-y-auto">
              {report.changes.added.map((file: string, idx: number) => (
                <div key={idx} className="text-sm font-mono text-green-300 py-1">
                  + {file}
                </div>
              ))}
            </div>
          </div>
        )}

        {report.changes?.removed?.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold text-red-400 mb-2">
              Removed Files ({report.changes.removed.length})
            </h3>
            <div className="bg-slate-950 rounded p-4 max-h-60 overflow-y-auto">
              {report.changes.removed.map((file: string, idx: number) => (
                <div key={idx} className="text-sm font-mono text-red-300 py-1">
                  - {file}
                </div>
              ))}
            </div>
          </div>
        )}

        {report.changes?.changed?.length > 0 && (
          <div className="mb-4">
            <h3 className="font-semibold text-yellow-400 mb-2">
              Modified Files ({report.changes.changed.length})
            </h3>
            <div className="bg-slate-950 rounded p-4 max-h-96 overflow-y-auto">
              {report.changes.changed.slice(0, 100).map((file: string, idx: number) => {
                const detail = report.details?.find((d: any) => d.file_path === file);
                return (
                  <div key={idx} className="py-2 border-b border-slate-800">
                    <div className="text-sm font-mono text-yellow-300">~ {file}</div>
                    {detail && (
                      <div className="text-xs text-slate-500 ml-4 mt-1">
                        {detail.baseline_mtime} → {detail.current_mtime}
                      </div>
                    )}
                  </div>
                );
              })}
              {report.changes.changed.length > 100 && (
                <div className="text-sm text-slate-500 mt-2 text-center">
                  ... and {report.changes.changed.length - 100} more (export to see all)
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
