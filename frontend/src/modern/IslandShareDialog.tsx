import { ReactNode, useEffect, useMemo, useState } from "react";

import { copyImageBlobToClipboard, shareImageFile, shareImageFiles, ShareImagePreview } from "../utils/shareCanvas";
import IslandDialog from "./IslandDialog";

type Props = {
  preview: ShareImagePreview | null;
  title: string;
  text?: string;
  onClose: () => void;
  extraActions?: ReactNode;
  previews?: ShareImagePreview[];
};

export default function IslandShareDialog({ preview, previews, title, text, onClose, extraActions }: Props) {
  const pages = useMemo(() => previews?.length ? previews : preview ? [preview] : [], [preview, previews]);
  const [pageIndex, setPageIndex] = useState(0);
  const active = pages[Math.min(pageIndex, Math.max(0, pages.length - 1))] ?? null;
  useEffect(() => () => {
    pages.forEach((item) => URL.revokeObjectURL(item.url));
  }, [pages]);

  if (!active) return null;

  return (
    <IslandDialog
      title={title}
      description="动森风格分享卡会根据内容自动长高，不会截断文字。"
      icon="growth"
      onClose={onClose}
      className="island-share-dialog"
      footer={(
        <>
          <button className="island-button island-button--quiet" type="button" onClick={() => void copyImageBlobToClipboard(active.blob)}>复制到剪贴板</button>
          <a className="island-button island-button--secondary" href={active.url} download={active.filename}>下载当前页</a>
          {pages.length > 1 ? <button className="island-button island-button--secondary" type="button" onClick={() => pages.forEach((item) => { const link = document.createElement("a"); link.href = item.url; link.download = item.filename; link.click(); })}>下载全部</button> : null}
          {pages.length > 1 ? <button className="island-button island-button--primary" type="button" onClick={() => void shareImageFiles(pages, title, text)}>分享全部</button> : null}
          <button className="island-button island-button--primary" type="button" disabled={!active.canNativeShare} onClick={() => void shareImageFile(active.blob, active.filename, title, text)}>系统分享</button>
          {extraActions}
        </>
      )}
    >
      <div className="island-share-preview">
        {pages.length > 1 ? <div className="mb-3 flex flex-wrap gap-2">{pages.map((_, index) => <button key={index} type="button" onClick={() => setPageIndex(index)} className={`island-button ${index === pageIndex ? "island-button--primary" : "island-button--quiet"}`}>第 {index + 1} 页</button>)}</div> : null}
        <img src={active.url} alt={`${title}预览`} />
        <p>{Math.max(1, Math.round(active.sizeBytes / 1024))} KB · {active.mimeType.replace("image/", "").toUpperCase()}</p>
      </div>
    </IslandDialog>
  );
}
