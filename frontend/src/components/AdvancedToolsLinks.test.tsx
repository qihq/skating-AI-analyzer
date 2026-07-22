import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AdvancedToolsLinks from "./AdvancedToolsLinks";

describe("AdvancedToolsLinks", () => {
  it("keeps every non-primary workflow discoverable", () => {
    render(
      <MemoryRouter>
        <AdvancedToolsLinks />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "历史记录" })).toHaveAttribute("href", "/history");
    expect(screen.getByRole("link", { name: "AI 追问" })).toHaveAttribute("href", "/analysis-chat");
    expect(screen.getByRole("link", { name: "Golden 标注" })).toHaveAttribute("href", "/golden");
    expect(screen.getByRole("link", { name: "诊断调试" })).toHaveAttribute("href", "/debug");
    expect(screen.getByRole("link", { name: "API 设置" })).toHaveAttribute("href", "/settings/api");
  });
});
