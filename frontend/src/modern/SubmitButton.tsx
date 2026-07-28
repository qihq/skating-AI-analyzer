import { ComponentProps, ReactNode, useEffect, useRef } from "react";

import { SubmitActionStatus } from "../hooks/useSubmitAction";
import { Button, Notification } from "./AnimalUi";

type Props = Omit<ComponentProps<typeof Button>, "loading" | "children"> & {
  status: SubmitActionStatus;
  children: ReactNode;
  loadingLabel?: ReactNode;
  successLabel?: ReactNode;
  error?: unknown;
};

function errorDescription(error: unknown) {
  return error instanceof Error && error.message ? error.message : "请检查网络后重试。";
}

/** Original Animal Island button with the app-wide async action feedback contract. */
export default function SubmitButton({
  status,
  children,
  loadingLabel = "正在提交...",
  successLabel = "已完成",
  error,
  className,
  disabled,
  ...props
}: Props) {
  const previousStatus = useRef<SubmitActionStatus>("idle");

  useEffect(() => {
    if (status === "error" && previousStatus.current !== "error") {
      Notification.error({ message: "操作未完成", description: errorDescription(error) });
    }
    previousStatus.current = status;
  }, [error, status]);

  const isSubmitting = status === "submitting";
  const isSuccess = status === "success";
  const label = isSubmitting ? loadingLabel : isSuccess ? successLabel : children;
  const combinedClassName = [className, "ice-submit-button", isSuccess ? "ice-submit-button--success" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <Button
      {...props}
      className={combinedClassName}
      disabled={disabled || isSubmitting}
      loading={isSubmitting}
      aria-live="polite"
      data-submit-status={status}
    >
      {isSuccess ? <span aria-hidden="true">✓</span> : null}
      {label}
    </Button>
  );
}
