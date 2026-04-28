import type { AvatarType, Skater } from "../api/client";

export type ChildView = "tantan" | "zhaozao";

const CHILD_VIEW_AVATAR_TYPE: Record<ChildView, AvatarType> = {
  tantan: "zodiac_rat",
  zhaozao: "zodiac_tiger",
};

const CHILD_VIEW_NAME_ALIASES: Record<ChildView, string[]> = {
  tantan: ["tantan", "坦坦"],
  zhaozao: ["zhaozao", "昭昭", "didi", "弟弟"],
};

export function childViewLabel(childView: ChildView) {
  return childView === "tantan" ? "坦坦" : "昭昭";
}

export function childViewAvatarType(childView: ChildView): AvatarType {
  return CHILD_VIEW_AVATAR_TYPE[childView];
}

export function childViewFromSkater(skater: Pick<Skater, "avatar_type" | "name"> | null | undefined): ChildView | null {
  if (!skater) {
    return null;
  }

  if (skater.avatar_type === "zodiac_rat") {
    return "tantan";
  }
  if (skater.avatar_type === "zodiac_tiger") {
    return "zhaozao";
  }

  const normalizedName = skater.name.trim().toLowerCase();
  if (CHILD_VIEW_NAME_ALIASES.tantan.some((alias) => alias.toLowerCase() === normalizedName)) {
    return "tantan";
  }
  if (CHILD_VIEW_NAME_ALIASES.zhaozao.some((alias) => alias.toLowerCase() === normalizedName)) {
    return "zhaozao";
  }

  return null;
}

export function findSkaterForChildView(skaters: Skater[], childView: ChildView): Skater | null {
  const byAvatarType = skaters.find((skater) => skater.avatar_type === CHILD_VIEW_AVATAR_TYPE[childView]);
  if (byAvatarType) {
    return byAvatarType;
  }

  const byName = skaters.find((skater) => {
    const normalizedName = skater.name.trim().toLowerCase();
    return CHILD_VIEW_NAME_ALIASES[childView].some((alias) => alias.toLowerCase() === normalizedName);
  });

  return byName ?? null;
}

export function pickSkaterIdForChildView(skaters: Skater[], childView: ChildView): string {
  return findSkaterForChildView(skaters, childView)?.id ?? skaters.find((skater) => skater.is_default)?.id ?? skaters[0]?.id ?? "";
}
