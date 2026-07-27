import { useRef, useState } from "react";

import { formatKeyframeTimestamp, type KeyframeEvidenceItem } from "../utils/keyframeEvidence";

type Props = {
  analysisId: string;
  items: KeyframeEvidenceItem[];
};

export default function CorrectionKeyframeReview({ analysisId, items }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [selected, setSelected] = useState<KeyframeEvidenceItem | null>(null);

  const seekToSelected = (item: KeyframeEvidenceItem) => {
    if (item.timestamp == null) return;
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
      {selected ? (
        <div className="mt-3 overflow-hidden rounded-[14px] bg-slate-950">
          <div className="flex items-center justify-between gap-3 px-3 py-2 text-xs text-slate-200">
            <span className="font-semibold">正在 Review：{selected.key} · {selected.label}</span>
            <span>{formatKeyframeTimestamp(selected.timestamp)}</span>
          </div>
          <video
            ref={videoRef}
            data-testid="correction-review-video"
            controls
            playsInline
            preload="metadata"
            src={`/api/analysis/${analysisId}/video`}
            onLoadedMetadata={(event) => {
              if (selected.timestamp != null) event.currentTarget.currentTime = selected.timestamp;
            }}
            className="aspect-video w-full bg-black object-contain"
          />
        </div>
      ) : (
        <p className="mt-2 text-center text-[11px] leading-5 text-blue-700">点击 T / A / L，在原视频中定位 Review</p>
      )}
    </div>
  );
}
