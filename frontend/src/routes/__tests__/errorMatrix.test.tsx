/* SECTION 19'S OPERATION-TO-STATE MATRIX, RENDERED ROW BY ROW, AND ASKED WHETHER ANYTHING SPINS.
 *
 * WHAT THIS ASKS THAT THE PER-SCREEN TESTS DO NOT. Each screen's own test file asserts what its surfaces SAY, in
 * the words that screen chose. This asks one question of every screen at once: that a state the matrix declares
 * has a real, static rendering, announced to a screen reader, with no loading indicator anywhere in the tree.
 * Motion is zero, so every state has to be a rendering rather than a gap papered over by a spinner, and a screen
 * that renders nothing while it waits is indistinguishable from one that has finished with nothing to show.
 *
 * THE READS ARE NOT ENUMERATED, AND THAT IS THE POINT. Settings makes six reads and Templates nine, and a list of
 * them here would be a second copy of what each screen fetches: the day a screen gains a tenth read, a list would
 * still pass while answering nine. So every api read is answered the same way at once, by prefix, and the shell's
 * own reads are passed ahead of that so the gate still opens. A screen's reading is outstanding while ANY of its
 * reads is, and a refusal outranks an outstanding read, which is what makes answering everything the way to reach
 * either state.
 *
 * THE SCREENS ARE NOT ENUMERATED EITHER. `SCREENS` is the table the sidebar renders and the keyboard chords
 * resolve against, so the sweep below is over the product's own list of destinations plus the two routes that are
 * not destinations: first run, and the redirect that chooses between them. An eighth screen is covered the day it
 * is added, and a screen with no static pending surface reddens here rather than in a review.
 *
 * WHAT IS NOT HERE. The rows the matrix states as notices rather than as surfaces -- a failed solve, a refused
 * pin, a refused confirmation, a replaced proposal, a stopped projection, an unreadable feed -- are in
 * `degradation.test.tsx`, because what has to be asserted about each is its volume, its pigment and the
 * capability it names, not that a screen drew a panel. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  areas,
  events,
  googleConnection,
  jsonHandler,
  pendingReads,
  readUnavailable,
  readyz,
  refusedReads,
  session,
  settings,
} from "../../testing/apiStub";
import { indicatorsIn } from "../../testing/indicators";
import { renderAt } from "../../testing/renderRoute";
import { SCREENS, SETUP_PATH, SIGN_IN_PATH } from "../../ui/domain/shell/navigation";
import { routes } from "..";
import { buildAreas, buildReview } from "../areas/__tests__/fixtures";
import { buildBacklog } from "../backlog/__tests__/fixtures";
import { stubBacklog } from "../backlog/__tests__/render";
import { buildCollectingBaseline, buildWeightSets } from "../learned/__tests__/fixtures";
import { buildEmptyDay } from "../today/__tests__/fixtures";
import { hostSpan, hostToday, stubDay } from "../today/__tests__/render";
import {
  EMPTY_WEEK_FACTS,
  WEEK_PATH,
  buildWeekView,
  installWeekReads,
} from "../week/__tests__/fixtures";

/** The two routes that are not destinations: first run, and the redirect that chooses where to land. */
const OFF_THE_SIDEBAR = [SETUP_PATH, "/"] as const;

/** Every path the real route table declares, so the sweep's own coverage is asked of the app. */
function routePaths(): string[] {
  const found: string[] = [];
  for (const route of routes) {
    if (route.path !== undefined) found.push(route.path);
    if (route.index === true) found.push("/");
    for (const child of route.children ?? []) {
      if (child.path !== undefined) found.push(child.path);
      if (child.index === true) found.push("/");
    }
  }
  return found;
}

/** Every path this sweep covers, derived from the product's own screen table. */
const PATHS: readonly string[] = [...SCREENS.map((one) => one.path), ...OFF_THE_SIDEBAR];

/* THE MODES, WHICH ARE ROWS OF THE MATRIX AND NOT SCREENS. The pie review and the weekly session are ways of
 * using a screen, so they carry no entry in `SCREENS` and the matrix names each one separately. */
const MODES: readonly string[] = ["/areas?mode=review", "/week?mode=session"];

/** The gate's own reads, answered so the shell opens whatever the screen under it is doing. */
const shellReads = () => [session(), events(), readyz()];

function noIndicator(root: ParentNode): void {
  expect(indicatorsIn(root)).toEqual([]);
}

describe("every screen, with every read it makes still outstanding", () => {
  it.each([...PATHS, ...MODES])("%s states what it is waiting for, in words", async (path) => {
    apiServer.use(...shellReads(), pendingReads());
    const { container } = renderAt(path);

    /* `role="status"` is the pending surface's own announcement, so this is the accessible reading rather than a
     * class: a screen that drew a static panel and told a screen-reader user nothing would pass a class check.
     *
     * ALL of them, because Settings narrows six reads into four readings and draws a pending surface per section.
     * Every one has to name what it is waiting for: a screen with three sentences and one blank panel is the
     * shape this asks about. */
    const waiting = await screen.findAllByRole("status");

    expect(waiting.length).toBeGreaterThan(0);
    for (const one of waiting) expect(one.textContent ?? "").toMatch(/^Reading/);
    noIndicator(container);
  });
});

describe("every screen, with every read refused", () => {
  it.each([...PATHS, ...MODES])(
    "%s states the failure and the api's own sentence",
    async (path) => {
      apiServer.use(...shellReads(), refusedReads());
      const { container } = renderAt(path);

      /* `role="alert"` because a failure interrupts, where an empty state is the screen's own content. The api's
       * `detail` is rendered verbatim: every problem this api produces says what was not applied and what is still
       * true, and a screen paraphrasing it would be writing the sentence twice.
       *
       * ALL of them, for the reason the pending sweep reads all of its own: Settings answers per section, so a
       * screen with three sentences and one blank panel is exactly what this asks about. */
      const failed = await screen.findAllByRole("alert");

      expect(failed.length).toBeGreaterThan(0);
      for (const one of failed) {
        expect(one.textContent ?? "").toContain(readUnavailable.detail);
        expect(one).toHaveClass("status--error");
      }
      noIndicator(container);
    },
  );
});

/* THE EMPTY STATES THE MATRIX NAMES, each with the action or the statement it owes the reader. An empty state is
 * the screen's own content rather than something that happened to it, so it is announced to nobody and carries no
 * role: what is asserted is the words and, where the matrix names one, the repair. */
describe("the empty states", () => {
  it("names the horizon and offers both of its repairs, on a week beyond it", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        emptyReason: "outside_horizon",
        emptyWeek: EMPTY_WEEK_FACTS,
      }),
    );
    const { container } = renderAt(WEEK_PATH);

    expect(await screen.findByText(EMPTY_WEEK_FACTS.statement)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /horizon/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /solve/i })).toBeInTheDocument();
    noIndicator(container);
  });

  it("names the missing input and its one repair, on a week nothing can be solved for", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        emptyReason: "setup_incomplete",
        emptyWeek: {
          ...EMPTY_WEEK_FACTS,
          missingInputs: ["day_shape"],
          statement: "No day shape exists, so nothing can be solved yet.",
        },
      }),
    );
    const { container } = renderAt(WEEK_PATH);

    expect(
      await screen.findByText("No day shape exists, so nothing can be solved yet."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Finish setting up" })).toBeInTheDocument();
    noIndicator(container);
  });

  it("prompts a capture on a backlog with nothing in it", async () => {
    stubBacklog({ backlog: buildBacklog({ header: { openCount: 0, atRiskCount: 0 }, tasks: [] }) });
    const { container } = renderAt("/backlog");

    expect(await screen.findByText("No task is in this list")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture the first one" })).toBeInTheDocument();
    noIndicator(container);
  });

  it("states that no block is planned on a day with none", async () => {
    stubDay(buildEmptyDay({ date: hostToday(), span: hostSpan() }));
    const { container } = renderAt("/today");

    expect(await screen.findByText("No blocks are planned for this day")).toBeInTheDocument();
    noIndicator(container);
  });

  /* COLLECTING IS INFORMATIONAL AND NEVER A WARNING: nothing is broken in the first fortnight, and marking it in
   * a signal pigment would teach the reader to distrust a working system. So the surface is asserted to carry no
   * failure class as well as to say the words. */
  it("states that a baseline is being collected, and does not mark it as a failure", async () => {
    apiServer.use(
      ...shellReads(),
      jsonHandler("/api/v1/learned", { status: 200, body: buildCollectingBaseline() }),
      jsonHandler("/api/v1/weight-sets", { status: 200, body: buildWeightSets() }),
    );
    const { container } = renderAt("/learned");

    expect(await screen.findByText("Collecting baseline")).toBeInTheDocument();
    expect(container.querySelectorAll(".status--error")).toHaveLength(0);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    noIndicator(container);
  });

  it("states that a quarter of confirmed data does not yet exist, in the pie review", async () => {
    const review = buildReview();
    apiServer.use(
      ...shellReads(),
      googleConnection(),
      settings(),
      jsonHandler("/api/v1/areas", { status: 200, body: buildAreas() }),
      jsonHandler("/api/v1/reviews/budget", { status: 200, body: review }),
      areas(),
    );
    const { container } = renderAt("/areas?mode=review");

    expect(await screen.findByText(review.proposal.statement)).toBeInTheDocument();
    noIndicator(container);
  });
});

describe("the sweep itself", () => {
  /* WHAT ACTUALLY GUARDS THE PATH LIST. `PATHS` is built from `SCREENS`, so asserting it contains every screen
   * cannot fail and reads as coverage it does not provide. What can fail is the pairing between the product's
   * screen table and its ROUTE table: a screen navigable with no route, or a route the sweep never renders. Both
   * are real, and the second is what this sweep depends on. */
  it("renders a route for every screen the sidebar navigates to", () => {
    const routed = routePaths();

    for (const one of SCREENS) expect(routed).toContain(one.path);
    expect(PATHS).toEqual([...SCREENS.map((one) => one.path), ...OFF_THE_SIDEBAR]);
  });

  it("leaves no route unswept but the ones that are not screens", () => {
    const unswept = routePaths().filter((path) => !PATHS.includes(path));

    /* Sign-in is outside the gate and the catch-all is not a destination: everything else the route table declares
     * is a path this sweep renders in both states. */
    expect(unswept.toSorted()).toEqual(["*", SIGN_IN_PATH]);
  });

  /* The instrument's own positive control. `indicatorsIn` returning an empty array is the passing answer
   * everywhere above, and an empty array is also what a reader that had stopped looking would return. */
  it("would report a spinner, a progress element and a busy region if a screen rendered one", () => {
    const host = document.createElement("div");
    host.innerHTML = `<div class="spinner"></div><progress></progress><p aria-busy="true">x</p>`;

    /* Three elements, and the spinner answers twice because two of the vocabularies match it. What matters is
     * that every one of the three is reported: a finding names the class so a reader can grep for it. */
    expect(indicatorsIn(host)).toHaveLength(4);
    expect(indicatorsIn(host).map((found) => found.className)).toContain("spinner");
  });
});
