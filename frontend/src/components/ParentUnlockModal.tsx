import PinInput from "./PinInput";
import IslandDialog from "../modern/IslandDialog";

type ParentUnlockModalProps = {
  pin: string;
  pinLength: number;
  error: string | null;
  failedAttempts: number;
  isSubmitting: boolean;
  locked: boolean;
  lockSecondsLeft: number;
  onChangePin: (value: string) => void;
  onClose: () => void;
  onSubmit: () => void;
};

export default function ParentUnlockModal({
  pin,
  pinLength,
  error,
  failedAttempts,
  isSubmitting,
  locked,
  lockSecondsLeft,
  onChangePin,
  onClose,
  onSubmit,
}: ParentUnlockModalProps) {
  return (
    <IslandDialog title="输入家长 PIN" description="验证后可上传训练视频、管理技能解锁与查看完整诊断细节。" icon="me" onClose={onClose} className="island-dialog__panel--compact" footer={<><button type="button" onClick={onClose} className="island-button island-button--secondary">取消</button><button type="button" onClick={onSubmit} disabled={isSubmitting || locked || pin.length !== pinLength} className="island-button island-button--primary">{isSubmitting ? <><span className="island-leaf-spinner" />验证中…</> : "进入家长模式"}</button></>}>
        <div className="island-pin-house"><div className="island-pin-house__roof" aria-hidden="true" /><p>打开居民服务处的家长钥匙</p>
          <PinInput
            length={pinLength}
            value={pin}
            onChange={onChangePin}
            autoFocus
            error={Boolean(error)}
            locked={locked}
            lockSecondsLeft={lockSecondsLeft}
            label="家长 PIN"
          />
        </div>
        {error ? <p className="island-dialog__error">{error}</p> : null}
        {failedAttempts > 0 && !error && !locked ? <p className="mt-4 text-center text-sm text-amber-500">已输错 {failedAttempts} 次。</p> : null}

    </IslandDialog>
  );
}
