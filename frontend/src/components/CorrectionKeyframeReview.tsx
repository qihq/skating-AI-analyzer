import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { formatKeyframeTimestamp, type KeyframeEvidenceItem } from "../utils/keyframeEvidence";

type Props = {
  analysisId: string;
  items: KeyframeEvidenceItem[];
};

export default function CorrectionKeyframeReview({ analysisId, items }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [selected, setSelected] = useState<KeyframeEvidenceItem | null>(null);
  const [frameReady, setFrameReady] = useState(false);

  useEffect(() => {
    if (!selected) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selected]);

  const seekToSelected = (item: KeyframeEvidenceItem) => {
    if (item.timestamp == null) return;
    setFrameReady(false);
    setSelected(item);
    const video = videoRef.current;
    if (video) {
      video.currentTime = item.timestamp;
      video.pause();
    }
  };

  return (
    <div className="mt-3 rounded-[16px] border border-blue-100 bg-blue-50/60 p-2.5">
      <div className="grid grid-cols-3 gap-2">
        {items.map((item) => {
          const active = selected?.key === item.key;
          return (
            <button
              key={item.key}
              type="button"
              disabled={item.timestamp == null}
              aria-label={`定位 ${item.key} ${item.label} ${formatKeyframeTimestamp(item.timestamp)}`}
              onClick={() => seekToSelected(item)}
              className={`min-h-[38px] rounded-full px-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
                active ? "bg-blue-600 text-white" : "border border-blue-200 bg-white text-blue-700 hover:bg-blue-100"
              }`}
            >
              {item.key} · {formatKeyframeTimestamp(item.timestamp)}
            </button>
          );
        })}
      </div>
      {!selected ? (
        <p className="mt-2 text-center text-[11px] leading-5 text-blue-700">点击 T / A / L，在原视频中定位 Review</p>
      ) : null}
      {selected
        ? createPortal(
            <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/70 p-3 backdrop-blur-sm tablet:p-6" role="dialog" aria-modal="true" aria-label="TAL 视频 Review">
              <div className="w-full max-w-4xl overflow-hidden rounded-[22px] border border-white/10 bg-slate-950 shadow-2xl">
                <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3 text-sm text-slate-100">
                  <div>
                    <p className="font-semibold">正在 Review：{selected.key} · {selected.label}</p>
                    <p className="mt-1 text-xs text-slate-400">{formatKeyframeTimestamp(selected.timestamp)} · {selected.frameId ?? selected.value}</p>
                  </div>
                  <button type="button" onClick={() => setSelected(null)} className="min-h-[36px] rounded-full bg-white/10 px-4 text-xs font-semibold text-white hover:bg-white/15">关闭</button>
                </div>
                <div className="relative aspect-video bg-black">
                  {!frameReady && selected.imageUrl ? <img src={selected.imageUrl} alt={`${selected.key} 定位预览`} className="absolute inset-0 z-10 h-full w-full object-contain" /> : null}
                  {!frameReady ? <div className="pointer-events-none absolute inset-x-0 bottom-3 z-20 mx-auto w-fit rounded-full bg-slate-950/80 px-3 py-1 text-xs text-white">正在定位原视频…</div> : null}
                  <video
                    ref={videoRef}
                    data-testid="correction-review-video"
                    controls
                    playsInline
                    preload="auto"
                    src={`/api/analysis/${analysisId}/video`}
                    onLoadedMetadata={(event) => {
                      if (selected.timestamp != null) event.currentTarget.currentTime = selected.timestamp;
                    }}
                    onSeeked={() => setFrameReady(true)}
                    onCanPlay={() => setFrameReady(true)}
                    className="h-full w-full bg-black object-contain"
                  />
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
