/* The route table.
 *
 * Every screen the sidebar and the keyboard can reach must have a route, and the assertions
 * below are how a later ticket finds out that it replaced a body rather than adding an entry. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../testing/apiServer";
import { readyz } from "../testing/apiStub";
import { renderAt } from "../testing/renderRoute";
import { SCREENS, SETUP_PATH } from "../ui/domain/shell/navigation";
import { DEFAULT_RETURN_PATH } from "../app/signIn";
import { routes } from ".";

function declaredPaths(): string[] {
  const [, shell] = routes;
  return (shell.children ?? []).flatMap((child) => (child.path === undefined ? [] : [child.path]));
}

describe("the route table", () => {
  it("declares a route for every screen the sidebar reaches", () => {
    const paths = declaredPaths();
    for (const child of SCREENS) expect(paths).toContain(child.path);
  });

  it("declares setup, which is a route rather than a modal", () => {
    expect(declaredPaths()).toContain(SETUP_PATH);
  });

  it("gives every screen its own keyboard letter", () => {
    const chords = SCREENS.map((child) => child.chord);
    expect(new Set(chords).size).toBe(chords.length);
  });

  it("uses the seven letters the keyboard map names", () => {
    expect(SCREENS.map((child) => child.chord)).toEqual(["w", "t", "b", "a", "m", "l", "s"]);
  });
});

describe("rendering each screen", () => {
  it.each(SCREENS.map((child) => [child.path, child.label] as const))(
    "%s renders a serif page title",
    async (path) => {
      apiServer.use(readyz());
      renderAt(path);
      expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    },
  );

  it("redirects the root to the week", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Week");
    expect(DEFAULT_RETURN_PATH).toBe("/week");
  });

  it("renders setup, which is reached from the root rather than from the sidebar", async () => {
    renderAt(SETUP_PATH);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Setup");
    expect(screen.queryByRole("link", { name: "setup" })).not.toBeInTheDocument();
  });

  it("renders sign-in outside the shell, so the gate has somewhere to send a visitor", async () => {
    renderAt("/sign-in?next=%2Fbacklog");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Sign in");
    expect(screen.queryByLabelText("Screens")).not.toBeInTheDocument();
    expect(screen.getByText("/backlog")).toBeInTheDocument();
  });
});
