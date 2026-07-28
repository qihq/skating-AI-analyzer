import { useCallback, useEffect, useRef, useState } from "react";

export type SubmitActionStatus = "idle" | "submitting" | "success" | "error";

type Options = {
  successDurationMs?: number;
  errorDurationMs?: number;
  onError?: (error: unknown) => void;
};

/** Keeps mutation feedback consistent and prevents duplicate in-flight requests. */
export function useSubmitAction({
  successDurationMs = 1_200,
  errorDurationMs = 4_500,
  onError,
}: Options = {}) {
  const [status, setStatus] = useState<SubmitActionStatus>("idle");
  const [error, setError] = useState<unknown>(null);
  const mountedRef = useRef(true);
  const inFlightRef = useRef(false);
  const resetTimerRef = useRef<number | null>(null);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => () => {
    mountedRef.current = false;
    if (resetTimerRef.current != null) window.clearTimeout(resetTimerRef.current);
  }, []);

  const scheduleReset = useCallback((delay: number) => {
    if (resetTimerRef.current != null) window.clearTimeout(resetTimerRef.current);
    resetTimerRef.current = window.setTimeout(() => {
      if (mountedRef.current) setStatus("idle");
      resetTimerRef.current = null;
    }, delay);
  }, []);

  const run = useCallback(async <T,>(action: () => Promise<T> | T): Promise<T | undefined> => {
    if (inFlightRef.current) return undefined;

    inFlightRef.current = true;
    if (resetTimerRef.current != null) window.clearTimeout(resetTimerRef.current);
    if (mountedRef.current) {
      setError(null);
      setStatus("submitting");
    }

    try {
      const result = await action();
      if (mountedRef.current) {
        setStatus("success");
        scheduleReset(successDurationMs);
      }
      return result;
    } catch (nextError) {
      if (mountedRef.current) {
        setError(nextError);
        setStatus("error");
        scheduleReset(errorDurationMs);
        onErrorRef.current?.(nextError);
      }
      throw nextError;
    } finally {
      inFlightRef.current = false;
    }
  }, [errorDurationMs, scheduleReset, successDurationMs]);

  return { status, error, isSubmitting: status === "submitting", run };
}
