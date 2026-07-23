import type { AnnualExport } from "../api/client";

interface AnnualExportStatusProps {
  exportJob: AnnualExport | null;
  onRetry?: () => void;
  retrying?: boolean;
}

export default function AnnualExportStatus({ exportJob, onRetry, retrying = false }: AnnualExportStatusProps) {
  if (!exportJob) return null;
  if (exportJob.status === "completed") {
    return (
      <div className="rounded-2xl bg-emerald-50 px-4 py-4 text-sm text-emerald-800">
        <p>年度 PDF 已生成（{exportJob.page_count ?? "?"} 页）。</p>
        <a className="mt-3 inline-flex font-semibold underline" href={`/api/annual/exports/${exportJob.id}/download`}>下载年度 PDF</a>
      </div>
    );
  }
  if (exportJob.status === "failed") {
    return (
      <div role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
        <p>{exportJob.error_message || "年度 PDF 生成失败，请检查字体配置后重试。"}</p>
        {onRetry ? <button type="button" className="mt-3 font-semibold underline" disabled={retrying} onClick={onRetry}>重新生成年度 PDF</button> : null}
      </div>
    );
  }
  return <p className="rounded-2xl bg-blue-50 px-4 py-3 text-sm text-blue-700">正在生成年度 PDF，请勿关闭此页面…</p>;
}
