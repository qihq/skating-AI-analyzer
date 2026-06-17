export function readVideoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    const cleanup = () => {
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
      video.load();
    };
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      cleanup();
      resolve(duration);
    };
    video.onerror = () => {
      cleanup();
      reject(new Error("video_metadata_unavailable"));
    };
    video.src = url;
  });
}

export function shouldShowManualWindow(duration: number | null) {
  return typeof duration === "number" && Number.isFinite(duration) && duration > 15;
}

export function validateManualWindow(start: string, end: string, duration: number | null) {
  const hasStart = start.trim() !== "";
  const hasEnd = end.trim() !== "";
  if (!hasStart && !hasEnd) {
    return null;
  }
  if (!hasStart || !hasEnd) {
    return "起止点需要同时填写。";
  }
  const startValue = Number(start);
  const endValue = Number(end);
  if (!Number.isFinite(startValue) || !Number.isFinite(endValue)) {
    return "起止点必须是数字。";
  }
  if (startValue < 0) {
    return "开始时间不能小于 0。";
  }
  if (endValue <= startValue) {
    return "结束时间必须大于开始时间。";
  }
  if (duration != null && duration > 0 && endValue > duration + 0.01) {
    return "结束时间不能超过视频总时长。";
  }
  return null;
}

export function appendManualWindow(formData: FormData, start: string, end: string) {
  if (!start.trim() || !end.trim()) {
    return;
  }
  formData.append("manual_action_window_start_sec", start.trim());
  formData.append("manual_action_window_end_sec", end.trim());
}
