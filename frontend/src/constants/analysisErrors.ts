export type ErrorAction = "重新上传" | "重新分析" | "去设置";

export type AnalysisErrorMessage = {
  title: string;
  hint: string;
  action: ErrorAction;
};

export const ERROR_MESSAGES: Record<string, AnalysisErrorMessage> = {
  VIDEO_FORMAT_INVALID: {
    title: "视频格式无法识别",
    hint: "请确认文件是真实的 MP4、MOV 或 AVI 视频，且文件未损坏",
    action: "重新上传",
  },
  VIDEO_NO_VIDEO_STREAM: {
    title: "视频缺少可分析画面",
    hint: "视频需要至少 0.5 秒、分辨率不低于 320×180，并包含可解码的视频流",
    action: "重新上传",
  },
  VIDEO_BLANK_FRAMES: {
    title: "视频画面过暗或无有效内容",
    hint: "检测到抽样画面接近纯黑，请重新上传能看清滑行者的视频",
    action: "重新上传",
  },
  VIDEO_DECODE_FAILED: {
    title: "视频格式无法识别",
    hint: "请确认视频文件未损坏，建议使用 MP4（H.264）格式",
    action: "重新上传",
  },
  FRAME_EXTRACT_FAILED: {
    title: "视频帧提取失败",
    hint: "视频可能过短（需至少 3 秒）或分辨率过低",
    action: "重新上传",
  },
  AI_API_TIMEOUT: {
    title: "AI 分析超时",
    hint: "可能是网络波动导致，通常重试一次即可解决",
    action: "重新分析",
  },
  AI_API_AUTH_ERROR: {
    title: "API Key 验证失败",
    hint: "请前往「设置 → API 配置」检查 API Key 是否正确填写",
    action: "去设置",
  },
  AI_API_QUOTA_EXCEEDED: {
    title: "API 额度不足",
    hint: "当前 API Key 的调用次数或 Token 额度已用完，请检查账户余额",
    action: "去设置",
  },
  AI_API_CONTENT_FILTER: {
    title: "内容被 AI 安全过滤",
    hint: "视频内容触发了 AI 供应商的安全检查，可尝试更换 AI 供应商",
    action: "重新分析",
  },
  AI_RESPONSE_PARSE_FAIL: {
    title: "AI 返回格式异常",
    hint: "AI 返回了无法解析的内容，通常重试一次即可",
    action: "重新分析",
  },
  REPORT_SAVE_FAILED: {
    title: "报告保存失败",
    hint: "可能是存储空间不足，请检查 NAS 磁盘剩余空间",
    action: "重新分析",
  },
  UNKNOWN_ERROR: {
    title: "未知错误",
    hint: "请查看系统日志，或联系开发者",
    action: "重新分析",
  },
};

export function getAnalysisErrorMessage(errorCode?: string | null): AnalysisErrorMessage {
  if (!errorCode) {
    return ERROR_MESSAGES.UNKNOWN_ERROR;
  }
  return ERROR_MESSAGES[errorCode] ?? ERROR_MESSAGES.UNKNOWN_ERROR;
}
