import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

export type SavedJumpFrameState = {
  analysisId: string; frameId: string; url: string;
  status: "loading" | "ready" | "error";
  isReady: () => boolean;
};
type Props = {
  analysisId: string; frameId: string; alt: string;
  onReady?: () => void;
  children?: (state: SavedJumpFrameState) => ReactNode;
};

/** Saved-only GET: each mounted request owns its availability and event lifetime. */
export default function SavedJumpFrame(props: Props) {
  const src = "/api/frames/" + encodeURIComponent(props.analysisId) + "/" + encodeURIComponent(props.frameId + ".jpg") + "?saved_only=true";
  return <FrameRequest key={src} {...props} src={src} />;
}

function FrameRequest({ analysisId, frameId, alt, onReady, children, src }: Props & { src: string }) {
  const [status, setStatus] = useState<SavedJumpFrameState["status"]>("loading");
  const phase = useRef(status);
  const active = useRef(false);
  useLayoutEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);
  const isReady = () => active.current && phase.current === "ready";
  return <>
    {status === "error" ? <p role="status">保存原帧不可用：{frameId}。没有补帧，请选择其他已保存帧。</p> : <>
      {status === "loading" ? <p role="status">保存原帧加载中：{frameId}，确认可用后才能定位视频。</p> : null}
      <img className="w-full object-contain" src={src} alt={alt} onLoad={() => {
        // Detached requests and duplicate/late events cannot revive or seek a frame.
        if (!active.current || phase.current !== "loading") return;
        phase.current = "ready"; setStatus("ready"); onReady?.();
      }} onError={() => {
        if (!active.current || phase.current === "error") return;
        phase.current = "error"; setStatus("error");
      }} />
    </>}
    {children?.({ analysisId, frameId, url: src, status, isReady })}
  </>;
}
