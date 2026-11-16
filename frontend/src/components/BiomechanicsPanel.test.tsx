import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import BiomechanicsPanel from "./BiomechanicsPanel";

afterEach(cleanup);

const JUMP_WARNING = "当前视频关键帧检测不稳定，生物力学指标已标记为数据异常。";
const PROFILE_WARNING = "证据不足，暂不能自动区分跳跃和旋转。当前选择仅用于分析路由，不能确认动作类型、周数或单跳/连跳。";
const REPORT_WARNING = "报告级分类提示：动作族尚未确认。";

describe("BiomechanicsPanel profile warning", () => {
  it("shows the profile warning alongside the jump warning without hiding metrics", () => {
    render(
      <BiomechanicsPanel
        mode="parent"
        bioData={{
          jump_metrics: { air_time_seconds: 0.42, estimated_height_cm: 18.5, takeoff_speed_mps: 2.1, rotation_rps: 1.2 },
          jump_metrics_status: "invalid",
          jump_metrics_warning: JUMP_WARNING,
          profile_warning: PROFILE_WARNING,
        }}
      />,
    );
    expect(screen.getByText(JUMP_WARNING)).toBeInTheDocument();
    const warning = screen.getByTestId("profile-evidence-warning");
    expect(warning).toHaveTextContent(PROFILE_WARNING);
    expect(screen.getByText("滞空时间")).toBeInTheDocument();
    expect(screen.getByText("0.42")).toBeInTheDocument();
    expect(screen.getByText("起跳速度")).toBeInTheDocument();
    expect(screen.getByText("2.10")).toBeInTheDocument();
    expect(screen.getByText("转速")).toBeInTheDocument();
  });

  it("does not duplicate a warning already shown as the jump warning", () => {
    render(
      <BiomechanicsPanel
        mode="parent"
        bioData={{
          jump_metrics: { air_time_seconds: 0.42 },
          jump_metrics_status: "invalid",
          jump_metrics_warning: PROFILE_WARNING,
          profile_warning: PROFILE_WARNING,
        }}
      />,
    );
    expect(screen.getAllByText(PROFILE_WARNING)).toHaveLength(1);
    expect(screen.queryByTestId("profile-evidence-warning")).not.toBeInTheDocument();
    expect(screen.getByText("0.42")).toBeInTheDocument();
  });

  it("uses the report warning ahead of the bio warning and keeps metrics visible", () => {
    render(
      <BiomechanicsPanel
        mode="child"
        reportWarning={REPORT_WARNING}
        bioData={{
          jump_metrics: { air_time_seconds: 0.5, estimated_height_cm: 20 },
          profile_warning: PROFILE_WARNING,
        }}
      />,
    );
    const warning = screen.getByTestId("profile-evidence-warning");
    expect(warning).toHaveTextContent(REPORT_WARNING);
    expect(warning).not.toHaveTextContent(PROFILE_WARNING);
    expect(screen.getByText("0.50")).toBeInTheDocument();
    expect(screen.getByText("20.0")).toBeInTheDocument();
  });

  it("leaves the jump warning visible when only the profile warning is blank", () => {
    render(
      <BiomechanicsPanel
        mode="parent"
        bioData={{
          jump_metrics: { air_time_seconds: 0.42 },
          jump_metrics_status: "invalid",
          jump_metrics_warning: JUMP_WARNING,
          profile_warning: "   ",
        }}
      />,
    );
    expect(screen.getByText(JUMP_WARNING)).toBeInTheDocument();
    expect(screen.queryByTestId("profile-evidence-warning")).not.toBeInTheDocument();
    expect(screen.getByText("0.42")).toBeInTheDocument();
  });

  it("does not hide metrics solely because profile evidence says route-only", () => {
    render(
      <BiomechanicsPanel
        mode="parent"
        bioData={{
          jump_metrics: { air_time_seconds: 0.42, estimated_height_cm: 18.5 },
          profile_warning: PROFILE_WARNING,
          profile_evidence: { route_only: true },
        }}
      />,
    );
    expect(screen.getByTestId("profile-evidence-warning")).toHaveTextContent(PROFILE_WARNING);
    expect(screen.getByText("滞空时间")).toBeInTheDocument();
    expect(screen.getByText("0.42")).toBeInTheDocument();
    expect(screen.getByText("起跳速度")).toBeInTheDocument();
  });

  it("shows the profile warning even when jump metrics are unavailable", () => {
    render(<BiomechanicsPanel mode="parent" bioData={{ profile_warning: PROFILE_WARNING }} />);
    expect(screen.getByTestId("profile-evidence-warning")).toHaveTextContent(PROFILE_WARNING);
  });
});
