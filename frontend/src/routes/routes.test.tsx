/* The route table.
 *
 * Every screen the sidebar and the keyboard can reach must have a route, and the assertions
 * below are how a later ticket finds out that it replaced a body rather than adding an entry. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../testing/apiServer";
import { readyz } from "../testing/apiStub";
import { renderAt } from "../testing/renderRoute";
import { MINIMUM_DECLARED, setupHandlers } from "./setup/__tests__/handlers";
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

  /* The root's decision needs a read, so this case installs one that lets a plan exist. Without handlers it still
   * lands on the week, through the REFUSED-read branch, and would read as though it had asserted the ready path.
   *
   * No assertion HERE can tell the two apart, because both answer with the week: what this case owns is that the
   * root has a route and lands on a real screen. Which answer the root gives, and why, is
   * `__tests__/RootRedirect.test.tsx`'s, where the two that answer with setup are what make the branch falsifiable. */
  it("redirects the root to the week once a plan can exist", async () => {
    apiServer.use(...setupHandlers(MINIMUM_DECLARED));
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

  /* Without the catch-all, an unmatched path rendered React Router's developer error page:
   * "Unexpected Application Error!", a "Hey developer" line with emoji, and an inline rgba() with a
   * hard-coded padding. Off-brand on six counts and reachable from the URL bar by a typo. */
  it("answers an unmatched path with a syncr surface, not the framework's error page", async () => {
    apiServer.use(readyz());
    renderAt("/wek");

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Not found");
    expect(screen.queryByText(/Unexpected Application Error/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Hey developer/)).not.toBeInTheDocument();
  });

  it("keeps the unmatched surface inside the gate and the shell", async () => {
    apiServer.use(readyz());
    renderAt("/nope/deeper/still");

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Not found");
    expect(screen.getByLabelText("Screens")).toBeInTheDocument();
  });
});
