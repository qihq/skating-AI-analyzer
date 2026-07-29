import { Button, Modal } from "./AnimalUi";
import SubmitButton from "./SubmitButton";

interface ModernConfirmModalProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export default function ModernConfirmModal({ open, title, description, confirmLabel, danger, loading, onCancel, onConfirm }: ModernConfirmModalProps) {
  return (
    <Modal
      open={open}
      title={title}
      typewriter={false}
      maskClosable={!loading}
      onClose={loading ? undefined : onCancel}
      footer={<div className="flex justify-end gap-3"><Button onClick={onCancel} disabled={loading}>取消</Button><SubmitButton type="primary" danger={danger} status={loading ? "submitting" : "idle"} loadingLabel="处理中..." onClick={onConfirm}>{confirmLabel}</SubmitButton></div>}
    >
      <p className="py-3 text-sm leading-7 text-slate-700">{description}</p>
    </Modal>
  );
}
