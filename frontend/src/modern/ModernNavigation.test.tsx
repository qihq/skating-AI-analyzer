import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { IslandDock, IslandRail } from "./ModernNavigation";

function renderNavigation(activeSpace?: "home" | "review" | "growth" | "me") {
  render(
    <MemoryRouter>
      <IslandDock activeSpace={activeSpace} />
      <IslandRail activeSpace={activeSpace} />
    </MemoryRouter>,
  );
}

describe("ModernNavigation", () => {
  it("keeps Start Review neutral outside the Review space", () => {
    renderNavigation("home");

    const [dockReview, railReview] = screen.getAllByRole("link", { name: /开始复盘/i });
    expect(dockReview).toHaveClass("island-dock__item--primary");
    expect(railReview).toHaveClass("island-rail__item--primary");
    expect(dockReview).not.toHaveClass("is-active");
    expect(railReview).not.toHaveClass("is-active");
  });

  it("activates Start Review in the Review space", () => {
    renderNavigation("review");

    for (const reviewLink of screen.getAllByRole("link", { name: /开始复盘/i })) {
      expect(reviewLink).toHaveClass("is-active");
    }
  });
});
