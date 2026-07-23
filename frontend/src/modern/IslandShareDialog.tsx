import { ReactNode, useEffect } from "react";

import { copyImageBlobToClipboard, shareImageFile, ShareImagePreview } from "../utils/shareCanvas";
import IslandDialog from "./IslandDialog";

type Props = {
  preview: ShareImagePreview | null;
  title: string;
  text?: string;
  onClose: () => void;
  extraActions?: ReactNode;
};

export default function IslandShareDialog({ preview, title, text, onClose, extraActions }: Props) {
  useEffect(() => () => {
    if (preview?.url) URL.revokeObjectURL(preview.url);
  }, [preview?.url]);

  if (!preview) return null;

  return (
    <IslandDialog
      title={title}
      description="动森风格分享卡会根据内容自动长高，不会截断文字。"
      icon="growth"
      onClose={onClose}
      className="island-share-dialog"
      footer={(
        <>
          <button className="island-button island-button--quiet" type="button" onClick={() => void copyImageBlobToClipboard(preview.blob)}>复制到剪贴板</button>
          <a className="island-button island-button--secondary" href={preview.url} download={preview.filename}>下载图片</a>
          <button className="island-button island-button--primary" type="button" disabled={!preview.canNativeShare} onClick={() => void shareImageFile(preview.blob, preview.filename, title, text)}>系统分享</button>
          {extraActions}
        </>
      )}
    >
      <div className="island-share-preview">
        <img src={preview.url} alt={`${title}预览`} />
        <p>{Math.max(1, Math.round(preview.sizeBytes / 1024))} KB · {preview.mimeType.replace("image/", "").toUpperCase()}</p>
      </div>
    </IslandDialog>
  );
}
