import { Button, Modal } from "./AnimalUi";

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
      footer={<div className="flex justify-end gap-3"><Button onClick={onCancel} disabled={loading}>取消</Button><Button type="primary" danger={danger} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></div>}
    >
      <p className="py-3 text-sm leading-7 text-slate-700">{description}</p>
    </Modal>
  );
}
