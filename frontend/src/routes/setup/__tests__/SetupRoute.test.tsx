/* `/setup` as a reader meets it: four numbered rows, a caret, and no bar.
 *
 * THESE ARE THE CLAIMS THE SCREEN EXISTS TO MAKE, so each is asserted against the rendered DOM rather than against
 * the step model, which `steps.test.ts` covers: the row a reader sees, the word beside it, the mark on it, and that
 * leaving the route and coming back leaves all of it where it was.
 *
 * THE PROGRESS-BAR CLAIM IS ASSERTED BY ROLE, not by a class name. `progressbar` is the role a bar would carry
 * whatever it was built from, so a bar added later fails this whichever component drew it. */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, pendingHandler } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import { MINIMUM_DECLARED, NOTHING_DECLARED, setupHandlers } from "./handlers";

const ledger = () => screen.getByRole("list", { name: "Setup steps" });

const rows = () => screen.getAllByRole("listitem");

const rowNamed = (label: string) => rows().find((row) => row.textContent?.includes(label)) ?? null;

describe("the setup ledger", () => {
  it("lists four numbered steps and nothing else", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(rows()).toHaveLength(4);
    expect(rows().map((row) => row.textContent?.slice(0, 2))).toEqual(["01", "02", "03", "04"]);
  });

  it("states that four things have to exist before syncr can solve", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    expect(
      await screen.findByText("Four things have to exist before syncr can solve."),
    ).toBeInTheDocument();
  });

  /* No progress bar, and it is a decision rather than an omission: motion is zero, and a bar would say less than
   * the rows do about which step is blocked. */
  it("draws no progress bar", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("marks the two minimum steps as required to solve and the other two as optional", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(rowNamed("Declare Areas and budgets")).toHaveTextContent("required to solve");
    expect(rowNamed("Connect an anchor source")).toHaveTextContent("optional");
    expect(rowNamed("Set the day bounds and the write target")).toHaveTextContent("optional");
  });

  it("puts the caret on the current step and on no other", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    const current = rows().filter((row) => row.getAttribute("aria-current") === "step");

    expect(current).toHaveLength(1);
    expect(current.at(0)).toHaveTextContent("Connect an anchor source");
  });

  /* A step blocked by an incomplete predecessor has to be visually distinct from one merely not started, so the
   * dependency is legible. The kit draws the distinction as a class, and the row says why in words. */
  it("distinguishes a blocked step from one merely not started, and says what blocks it", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    const blocked = rowNamed("Build one day shape");
    const notStarted = rowNamed("Declare Areas and budgets");

    expect(blocked?.className).toContain("wizard__step--blocked");
    expect(notStarted?.className).not.toContain("wizard__step--blocked");
    expect(blocked).toHaveTextContent("blocked until an Area exists");
  });

  it("shows a completed step's status mark and its summary count", async () => {
    apiServer.use(...setupHandlers({ ...NOTHING_DECLARED, sources: 2 }));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    const done = rowNamed("Connect an anchor source");

    expect(done).toHaveTextContent("2 sources");
    expect(done?.querySelector(".wizard__mark--done")).not.toBeNull();
  });

  it("says nothing is outstanding once every step is done", async () => {
    apiServer.use(...setupHandlers({ ...MINIMUM_DECLARED, sources: 1, hasWriteTarget: true }));
    renderAt("/setup");

    expect(await screen.findByText("Nothing here is outstanding")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the week" })).toHaveAttribute("href", "/week");
  });
});

describe("the current step's panel", () => {
  it("links to the screen that authors the step, as a real link", async () => {
    apiServer.use(...setupHandlers({ ...NOTHING_DECLARED, sources: 1 }));
    renderAt("/setup");

    const link = await screen.findByRole("link", { name: "Declare Areas" });
    expect(link).toHaveAttribute("href", "/areas");
  });

  it("offers no link on a blocked step, because the work cannot be done yet", async () => {
    /* Areas absent blocks the day shape. Reaching that panel needs the two steps before it settled, which is a
       tenant with a source and no Areas: the caret then sits on Areas, so the day-shape panel is not the current
       one. What this asserts instead is that the ledger's own blocked row offers nothing to follow. */
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(rowNamed("Build one day shape")?.querySelector("a")).toBeNull();
  });

  it("names the step's own subject rather than a generic continue", async () => {
    apiServer.use(...setupHandlers({ ...NOTHING_DECLARED, sources: 1, areas: 1 }));
    renderAt("/setup");

    const link = await screen.findByRole("link", { name: "Build a day shape" });
    expect(link).toHaveAttribute("href", "/templates");
  });
});

/* PROGRESS IS SERVER STATE, WHICH IS WHY THERE IS NOTHING TO LOSE. Setup is a route rather than a modal because
 * configuration spans sittings, and the claim that makes it worth being a route is this one. */
describe("leaving and coming back", () => {
  it("preserves progress, because each step is done when the thing it asks for exists", async () => {
    apiServer.use(...setupHandlers({ ...NOTHING_DECLARED, sources: 2, areas: 3 }));
    const first = renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(rowNamed("Connect an anchor source")).toHaveTextContent("2 sources");
    expect(rowNamed("Declare Areas and budgets")).toHaveTextContent("3 Areas");

    first.unmount();
    renderAt("/setup");

    await waitFor(() => expect(ledger()).toBeInTheDocument());
    expect(rowNamed("Connect an anchor source")).toHaveTextContent("2 sources");
    expect(rowNamed("Declare Areas and budgets")).toHaveTextContent("3 Areas");
    expect(rows().find((row) => row.getAttribute("aria-current") === "step")).toHaveTextContent(
      "Build one day shape",
    );
  });
});

describe("before the reads land, and when they refuse", () => {
  it("names what is outstanding rather than spinning", async () => {
    /* Requests that never answer, so the pending surface is asserted deterministically rather than raced. */
    apiServer.use(
      pendingHandler("/api/v1/areas"),
      pendingHandler("/api/v1/templates"),
      pendingHandler("/api/v1/week-pattern"),
      pendingHandler("/api/v1/calendar-sources"),
    );
    renderAt("/setup");

    expect(await screen.findByText("Reading what you have declared so far")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("renders the api's own sentence when a read is refused", async () => {
    apiServer.use(
      /* First in the list, so it wins: msw answers with the first matching handler. The Areas read is the one the
         whole ledger is decided from, and a refusal outranks the three reads that landed. */
      jsonHandler("/api/v1/areas", {
        status: 503,
        body: {
          type: "syncr:dependency-unavailable",
          title: "The database is unavailable",
          status: 503,
          detail:
            "Areas could not be read. Nothing was changed, and reading your calendars still works.",
        },
      }),
      ...setupHandlers(NOTHING_DECLARED),
    );
    renderAt("/setup");

    expect(
      await screen.findByText(
        "Areas could not be read. Nothing was changed, and reading your calendars still works.",
      ),
    ).toBeInTheDocument();
  });
});
