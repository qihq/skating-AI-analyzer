import type { ExperienceEvent } from "./contracts";

const FAMILY_LABELS: Record<string, string> = {
  jump: "跳跃",
  spin: "旋转",
  step: "步法",
  spiral: "燕式",
  unknown: "未知动作",
};

const STATE_LABELS: Record<string, string> = {
  confirmed: "已确认",
  ambiguous: "有歧义",
  unknown: "未知",
};

export function actionFamilyLabel(profile: string | null | undefined): string {
  return profile ? FAMILY_LABELS[profile] ?? profile : "未知动作";
}

export function actionStateLabel(state: ExperienceEvent["state"]): string {
  return state ? STATE_LABELS[state] ?? "未知" : "未知";
}

export function actionEventLabel(event: Pick<ExperienceEvent, "profile" | "state" | "subtype">): string {
  return `${actionFamilyLabel(event.profile)}${event.subtype ? ` · ${event.subtype}` : ""} · ${actionStateLabel(event.state)}`;
}
