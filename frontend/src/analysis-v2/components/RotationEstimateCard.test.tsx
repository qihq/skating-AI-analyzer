import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RotationEstimateV2 } from "../contracts";
import RotationEstimateCard, { competitionNamingLanguage, rotationEstimateLanguage } from "./RotationEstimateCard";

const base = { schemaVersion: "rotation-estimate.v2" as const, eventId: "e1", profile: "jump" as const, definitionVersion: "airborne-body-rotation.source-pts.v1", confidence: .8, valueConvention: "airborne_body_rotation" as const, competitionConvention: "not_applied" as const, competitionNamingTurns: null, competitionNamingClass: null, subtypeSupport: null, phases: [], signals: [], evidenceSummary: [], conflicts: [], warnings: [], estimatorFingerprint: "est", sourceTimelineFingerprint: "pts", reviewRequired: false };

describe("RotationEstimateCard", () => {
  it("renders exact airborne rotation separately from Axel competition naming", () => {
    const rotation: RotationEstimateV2 = { ...base, status: "exact", valueTurns: 1.5, rangeTurns: null, classTurns: 1.5, classKind: "half_integer", observability: "observed", refusalReason: null, competitionConvention: "axel", competitionNamingTurns: 1.5, competitionNamingClass: "single_axel", subtypeSupport: .9 };
    render(<RotationEstimateCard rotation={rotation} />);
    expect(screen.getByText("空中身体转体 1.5 圈")).toBeInTheDocument();
    expect(screen.getByText(/比赛命名：single axel/)).toBeInTheDocument();
  });

  it("never rounds a range and uses family language for refusal", () => {
    const range: RotationEstimateV2 = { ...base, status: "range", valueTurns: null, rangeTurns: [1.5, 2.25], classTurns: null, classKind: null, confidence: .4, observability: "partial", refusalReason: "signal_aliasing", reviewRequired: true };
    const refusal: RotationEstimateV2 = { ...base, status: "unobservable", valueTurns: null, rangeTurns: null, classTurns: null, classKind: null, confidence: 0, observability: "unobservable", refusalReason: "occlusion" };
    expect(rotationEstimateLanguage(range)).toBe("空中身体转体约 1.5–2.25 圈");
    expect(rotationEstimateLanguage(refusal)).toBe("画面不足，暂不判断");
    expect(competitionNamingLanguage(refusal)).toBeNull();
  });

  it("uses observed-spin language instead of airborne language for a spin", () => {
    const spin: RotationEstimateV2 = {
      ...base,
      profile: "spin",
      definitionVersion: "observed-spin-rotation.source-pts.v1",
      valueConvention: "observed_spin_rotation",
      status: "exact",
      valueTurns: 3,
      rangeTurns: null,
      classTurns: 3,
      classKind: "integer",
      observability: "observed",
      refusalReason: null,
      phases: [{ phase: "spin_main", status: "exact", valueTurns: 3, rangeTurns: null, confidence: .9, observability: "observed", refusalReason: null }],
    };
    render(<RotationEstimateCard rotation={spin} />);
    expect(screen.getByText("旋转主体观察圈数 3 圈")).toBeInTheDocument();
    expect(screen.queryByText(/空中身体转体 3 圈/)).not.toBeInTheDocument();
  });
});
