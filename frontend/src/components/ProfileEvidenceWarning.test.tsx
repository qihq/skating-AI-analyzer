import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ProfileEvidenceWarning, { resolveProfileWarning } from "./ProfileEvidenceWarning";

afterEach(cleanup);

const REPORT_WARNING = "报告提示：本次证据不足，动作类别尚未确认。";
const BIO_WARNING = "生物力学提示：当前证据不足以确认旋转周数。";

describe("ProfileEvidenceWarning", () => {
  it("renders backend warning text as a readable accessible status", () => {
    render(<ProfileEvidenceWarning reportWarning={REPORT_WARNING} />);
    const warning = screen.getByTestId("profile-evidence-warning");
    expect(warning).toHaveAttribute("role", "status");
    expect(warning).toHaveAccessibleName("分类不确定提示");
    expect(warning).toHaveTextContent(REPORT_WARNING);
    expect(screen.getByText(REPORT_WARNING)).toBeInTheDocument();
  });

  it("prefers the report warning over the bio warning", () => {
    render(<ProfileEvidenceWarning reportWarning={REPORT_WARNING} bioWarning={BIO_WARNING} />);
    const warning = screen.getByTestId("profile-evidence-warning");
    expect(warning).toHaveTextContent(REPORT_WARNING);
    expect(warning).not.toHaveTextContent(BIO_WARNING);
  });

  it("falls back to the bio warning when the report warning is blank", () => {
    render(<ProfileEvidenceWarning reportWarning="  " bioWarning={BIO_WARNING} />);
    expect(screen.getByTestId("profile-evidence-warning")).toHaveTextContent(BIO_WARNING);
  });

  it("trims surrounding whitespace from the warning", () => {
    render(<ProfileEvidenceWarning reportWarning={`  ${REPORT_WARNING}  `} />);
    expect(screen.getByTestId("profile-evidence-warning").textContent).toBe(REPORT_WARNING);
  });

  it("renders nothing when both warnings are blank", () => {
    const { container } = render(<ProfileEvidenceWarning reportWarning={"\n\t"} bioWarning="   " />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not create a warning without backend warning text", () => {
    const { container } = render(<ProfileEvidenceWarning reportWarning={null} bioWarning={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("selects warning text without interpreting a profile value", () => {
    expect(resolveProfileWarning("", "")).toBe("");
    expect(resolveProfileWarning(REPORT_WARNING, BIO_WARNING)).toBe(REPORT_WARNING);
    expect(resolveProfileWarning(" ", BIO_WARNING)).toBe(BIO_WARNING);
  });
});
