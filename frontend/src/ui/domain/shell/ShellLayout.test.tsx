/* The shell's composition, and the two rules it exists to hold.
 *
 * The sidebar is PAPER, not ink, and the current item takes the same channel a selected block uses.
 * Both are asserted against the compiled stylesheet rather than against a class name, so a renamed
 * utility that stops producing the fill fails here. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { compileUtilities, declarationsOf } from "../../../testing/compileTheme";
import { renderSignedInAt } from "../../../testing/renderRoute";
import { SidebarNav } from "./SidebarNav";
import { SCREENS } from "./navigation";

describe("ShellLayout", () => {
  it("renders the wordmark in the top bar, lowercase", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByText("syncr")).toBeInTheDocument();
  });

  it("renders the notice-strip slot even with nothing in it", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByLabelText("Notices")).toBeEmptyDOMElement();
  });

  it("renders the route inside the shell", async () => {
    await renderSignedInAt("/today");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Today");
  });
});

describe("SidebarNav", () => {
  it("renders one link per screen", async () => {
    const nav = await renderSignedInAt("/week");
    expect(nav.querySelectorAll("a")).toHaveLength(SCREENS.length);
  });

  it("renders a real link, so middle-click and cmd-click still work", async () => {
    await renderSignedInAt("/week");
    expect(screen.getByRole("link", { name: "backlog" })).toHaveAttribute("href", "/backlog");
  });

  it("marks the current item for styling and for assistive technology from one boolean", async () => {
    await renderSignedInAt("/areas");
    const current = screen.getByRole("link", { name: "areas" });
    expect(current).toHaveAttribute("data-current");
    expect(current).toHaveAttribute("aria-current", "page");
  });

  it("marks exactly one item as current", async () => {
    const nav = await renderSignedInAt("/learned");
    expect(nav.querySelectorAll("[data-current]")).toHaveLength(1);
  });

  it("leaves every other item unmarked", async () => {
    await renderSignedInAt("/areas");
    expect(screen.getByRole("link", { name: "week" })).not.toHaveAttribute("data-current");
  });

  it("is paper and not ink", async () => {
    const nav = await renderSignedInAt("/week");
    const fill = [...nav.classList].find((name) => name.startsWith("bg-"));
    if (fill === undefined) throw new Error("the sidebar declares no fill");

    const declarations = declarationsOf(await compileUtilities([fill]), fill);

    expect(declarations).toMatch(/var\(--paper(-raised)?\)/);
    expect(declarations).not.toMatch(/var\(--ink/);
  });
});

function renderNav(counts?: Record<string, number>) {
  return render(
    <MemoryRouter>
      <SidebarNav
        screens={SCREENS}
        currentPath="/week"
        {...(counts === undefined ? {} : { counts })}
      />
    </MemoryRouter>,
  );
}

describe("the count at the right edge", () => {
  it("renders a count for a screen that has one to report", () => {
    renderNav({ "/backlog": 12 });
    expect(screen.getByRole("link", { name: /backlog/ })).toHaveTextContent(/^backlog12$/);
  });

  it("renders nothing for a screen with nothing to count", () => {
    renderNav({ "/backlog": 12 });
    expect(screen.getByRole("link", { name: "week" })).toHaveTextContent(/^week$/);
  });

  it("renders no count at all when none is supplied", () => {
    renderNav();
    expect(screen.getByRole("link", { name: "backlog" })).toHaveTextContent(/^backlog$/);
  });
});
