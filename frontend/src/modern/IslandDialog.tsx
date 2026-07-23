import { ReactNode, useEffect } from "react";

import IslandIcon from "./IslandIcon";

type IslandDialogProps = {
  open?: boolean;
  title: string;
  description?: string;
  icon?: "home" | "review" | "growth" | "me";
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  className?: string;
};

export default function IslandDialog({ open = true, title, description, icon = "me", children, footer, onClose, className = "" }: IslandDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="island-dialog" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="island-dialog-title" className={`island-dialog__panel ${className}`.trim()} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
        <header className="island-dialog__header">
          <span className="island-dialog__icon"><IslandIcon name={icon} /></span>
          <div><p>IceBuddy Island</p><h2 id="island-dialog-title">{title}</h2>{description ? <span>{description}</span> : null}</div>
          <button type="button" className="island-dialog__close" aria-label="关闭" onClick={onClose}>✕</button>
        </header>
        <div className="island-dialog__body">{children}</div>
        {footer ? <footer className="island-dialog__footer">{footer}</footer> : null}
      </section>
    </div>
  );
}
