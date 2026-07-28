import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Notification } from "./AnimalUi";
import SubmitButton from "./SubmitButton";

describe("SubmitButton", () => {
  it("uses the original button loading state and success feedback", () => {
    const { rerender } = render(<SubmitButton status="submitting">保存</SubmitButton>);
    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent("正在提交...");

    rerender(<SubmitButton status="success">保存</SubmitButton>);
    expect(button).toHaveTextContent("✓已完成");
    expect(button).toHaveAttribute("data-submit-status", "success");
  });

  it("announces an error once per error transition", () => {
    const error = vi.spyOn(Notification, "error");
    const { rerender } = render(<SubmitButton status="idle">保存</SubmitButton>);
    rerender(<SubmitButton status="error" error={new Error("网络断开")}>保存</SubmitButton>);
    expect(error).toHaveBeenCalledWith(expect.objectContaining({ message: "操作未完成", description: "网络断开" }));
    rerender(<SubmitButton status="error" error={new Error("网络断开")}>保存</SubmitButton>);
    expect(error).toHaveBeenCalledTimes(1);
    error.mockRestore();
  });
});
