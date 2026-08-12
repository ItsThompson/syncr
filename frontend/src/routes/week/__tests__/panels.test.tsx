/* THE PANELS AND THE BANDS: the verdict, the detail panel, a proposal, a conflict, and the two controls.
 *
 * WHAT THESE ANSWER is whether the payload the api serves reaches the words a reader reads, through the real route and
 * the real client. The wording, the zone a deadline is read in, the order the concessions and the gaps appear in, and
 * which channel a proposal target spends are all decisions this screen makes from one response.
 *
 * THE FIXTURE IS TYPED AGAINST THE GENERATED CLIENT, so a field renamed on the wire is a compile error here rather
 * than a test that passes against a shape the api cannot produce. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { renderAt } from "../../../testing/renderRoute";
import {
  AREA_FITNESS,
  BLOCK_LEETCODE,
  ISO_WEEK,
  LEETCODE,
  ROUTINE_ID,
  TASK_ID,
  WEEK_PATH,
  buildAdjustment,
  buildBlock,
  buildBlockChange,
  buildConflict,
  buildOperation,
  buildPin,
  buildPlan,
  buildProposal,
  buildShortfall,
  buildTradeoff,
  buildVerdict,
  buildWeekView,
  installWeekReads,
  monday,
} from "./fixtures";
import { WIDE_MIN_WIDTH_PX } from "../panelRoom";
import type { WeekView } from "../../../api/hooks/useWeek";

const WEEK = `${window.location.origin}/api/v1/weeks/${ISO_WEEK}`;

/* THE WIDTH IS SET WHERE A CASE DEPENDS ON IT. The panel opens unasked where there is room for its own column, so the
 * cases below that turn on the rail state which side of --bp-wide they render at rather than inheriting jsdom's own
 * width. Restored after each case, so one narrow render does not decide the next one. */
const JSDOM_WIDTH = window.innerWidth;

afterEach(() => {
  window.innerWidth = JSDOM_WIDTH;
});

async function renderWeek(view: WeekView) {
  const reads = installWeekReads(view);
  renderAt(WEEK_PATH);
  await screen.findByLabelText(`${LEETCODE} · Career`);
  return reads;
}

function panel(): HTMLElement {
  return screen.getByLabelText("Verdict");
}

/** The open state as the surface publishes it, which is the form a rule can select on. */
function panelState(): string | null {
  return document.querySelector("[data-panel]")?.getAttribute("data-panel") ?? null;
}

describe("the verdict the week serves", () => {
  it("states the provenance, the shortfall, the commitment, the deadline and the constraint", async () => {
    await renderWeek(buildWeekView({ verdict: buildVerdict() }));

    const verdict = panel();
    expect(within(verdict).getByText("capacity check")).toBeInTheDocument();
    expect(within(verdict).getByText("1h20m short")).toBeInTheDocument();
    expect(within(verdict).getByText("F&F Past Papers")).toBeInTheDocument();
    expect(within(verdict).getByText("Fitness floor 5h")).toBeInTheDocument();
    /* THE DEADLINE READS IN THE WEEK'S OWN ZONE. 09:00 UTC on Friday 13 February is Friday 09:00 in London, and a
     * reader east of their own plan would otherwise meet it as Saturday. */
    expect(within(verdict).getByText("Fri 09:00")).toBeInTheDocument();
  });

  it("lists the concessions this week has absorbed above the gaps", async () => {
    await renderWeek(
      buildWeekView({
        verdict: buildVerdict(),
        adjustments: [
          buildAdjustment({ kind: "breach_floor", targetId: AREA_FITNESS, deltaMinutes: 80 }),
          buildAdjustment({
            id: "7a1c4e02-0000-4000-8000-000000000002",
            kind: "reduce_routine",
            targetId: ROUTINE_ID,
            deltaMinutes: null,
            reductions: { "2026-02-09": 20, "2026-02-10": 20, "2026-02-11": 20 },
          }),
        ],
      }),
    );

    const rows = [...panel().querySelectorAll(".verdict-panel__row")].map(
      (row) => row.textContent ?? "",
    );
    expect(rows[0]).toContain("An Area floor was breached for this week, by 1h20m");
    expect(rows[1]).toContain("A routine was shortened for this week, by 1h across 3 dates");
    expect(rows[2]).toContain("F&F Past Papers");
  });

  it("reads the panel's lead sentence from the same narrowing the strip's cell reads", async () => {
    await renderWeek(buildWeekView({ verdict: buildVerdict() }));

    /* ONE WORDING, TWO SURFACES: the strip's verdict cell and the panel's headline. They are two renderings of one
     * narrowing, which is what stops the strip and the panel stating one week two ways. */
    expect(screen.getAllByText("This week cannot hold its commitments")).toHaveLength(2);
    expect(screen.getByText("1h20m short on F&F Past Papers before Fri 09:00")).toBeInTheDocument();
  });

  it("never claims a week is feasible on probe evidence alone", async () => {
    await renderWeek(
      buildWeekView({
        verdict: buildVerdict({ shortfalls: [], tradeoffs: [], capacityIsSufficient: true }),
      }),
    );

    expect(
      within(panel()).getByText("No shortfall found in this week's capacity"),
    ).toBeInTheDocument();
  });

  it("says a gap has no remedy rather than leaving a silence", async () => {
    /* A SERVED SOLVER VERDICT CARRIES NO TRADEOFFS TODAY (ticket 1440), so this is the shape a packing failure arrives
     * in: a gap with nothing offered against it. */
    await renderWeek(
      buildWeekView({
        verdict: buildVerdict({
          provenance: "solver",
          shortfalls: [buildShortfall({ kind: "minimum_chunk_unplaceable" })],
          tradeoffs: [],
        }),
      }),
    );

    expect(within(panel()).getByText(/names no concession/)).toBeInTheDocument();
    expect(within(panel()).getByText("authoritative")).toBeInTheDocument();
  });
});

describe("a tradeoff", () => {
  it("dispatches a solve against modified inputs and mutates nothing else", async () => {
    const reads = await renderWeek(buildWeekView({ verdict: buildVerdict() }));
    const requested: unknown[] = [];
    apiServer.use(
      http.post(`${WEEK}/tradeoffs`, async ({ request }) => {
        requested.push(await request.json());
        return HttpResponse.json(buildOperation({ status: "pending" }), { status: 202 });
      }),
    );
    const before = reads.weekReads();

    await userEvent.click(within(panel()).getByRole("button", { name: "Propose" }));

    await waitFor(() => expect(requested).toHaveLength(1));
    expect(requested[0]).toEqual({ kind: "accept_partial", targetId: TASK_ID });
    /* REQUESTING PERSISTS NOTHING, so the week is not read again: the result lands in the pending slot when the solve
     * does, and the push is what says so. */
    expect(reads.weekReads()).toBe(before);
  });

  it("offers one control per gap and selects none of them", async () => {
    await renderWeek(
      buildWeekView({
        verdict: buildVerdict({
          tradeoffs: [
            buildTradeoff(),
            buildTradeoff({ kind: "drop_item", targetId: ROUTINE_ID, label: "Drop Read" }),
          ],
        }),
      }),
    );

    expect(within(panel()).getAllByRole("button", { name: "Propose" })).toHaveLength(2);
    expect(
      panel().querySelectorAll("[aria-pressed], [aria-selected], [data-selected]"),
    ).toHaveLength(0);
  });
});

describe("the detail panel", () => {
  it("opens on selection and states the block's definition rows", async () => {
    await renderWeek(buildWeekView());

    await userEvent.click(screen.getByLabelText(`${LEETCODE} · Career`));

    const detail = await screen.findByLabelText("Detail");
    expect(within(detail).getByText(LEETCODE)).toBeInTheDocument();
    expect(within(detail).getByText("when")).toBeInTheDocument();
    expect(within(detail).getByText("Mon 09:00 to 10:30")).toBeInTheDocument();
    expect(within(detail).getByText("source")).toBeInTheDocument();
    expect(within(detail).getByText("authority")).toBeInTheDocument();
  });

  it("does not open on hover, because a reason is not a tooltip", async () => {
    await renderWeek(buildWeekView());

    await userEvent.hover(screen.getByLabelText(`${LEETCODE} · Career`));

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
  });

  /* WHERE THERE IS ROOM FOR THE PANEL'S COLUMN, SELECTION IS THE WHOLE GESTURE. That is the design language's own
   * trigger -- the reason arrives on selection and never on hover -- and it is why the state defaults open at this
   * width rather than making a reader ask twice for something already on the screen. */
  it("is open where there is room, so selecting a block alone renders it", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX;
    await renderWeek(buildWeekView());

    await userEvent.keyboard("j");

    const detail = await screen.findByLabelText("Detail");
    expect(within(detail).getByText(LEETCODE)).toBeInTheDocument();
  });

  /* THE OTHER EDGE OF THE SAME DEFAULT, one pixel below the threshold: the panel's column would take the width a day
   * column needs for a legible title, so the panel starts closed and the rail is what the reader has instead. */
  it("starts closed where there is no room, and the rail's own control opens it", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    await renderWeek(buildWeekView());
    await userEvent.keyboard("j");
    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open the detail panel" }));

    const detail = await screen.findByLabelText("Detail");
    expect(within(detail).getByText(LEETCODE)).toBeInTheDocument();
  });

  it("closes from the rail's control as well, which is the same control renamed", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    await renderWeek(buildWeekView());
    await userEvent.click(screen.getByLabelText(`${LEETCODE} · Career`));
    await screen.findByLabelText("Detail");

    await userEvent.click(
      screen.getByRole("button", { name: "Close the detail panel to its rail" }),
    );

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
    /* THE SELECTION SURVIVES CLOSING FROM THE RAIL. Only `Escape` clears it, so a reader who wanted the grid back
     * keeps the block they were reading about and can open the panel again on it. */
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toHaveAttribute("data-selected");
  });

  /* THE STATE TRAVELS AS AN ATTRIBUTE, which is what lets a rule select on it without a second copy of the condition.
   * One element carries it, asserted, because two would be two states named the same thing. */
  it("carries the open state as data-panel, in one place", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    await renderWeek(buildWeekView());

    expect(document.querySelectorAll("[data-panel]")).toHaveLength(1);
    expect(panelState()).toBe("closed");

    await userEvent.click(screen.getByLabelText(`${LEETCODE} · Career`));
    expect(panelState()).toBe("open");

    await userEvent.keyboard("{Escape}");
    expect(panelState()).toBe("closed");
  });

  it("renders the reason as labelled rows and never as a paragraph", async () => {
    await renderWeek(
      buildWeekView({
        live: buildPlan({
          blocks: [
            buildBlock({
              pinned: true,
              objectiveDelta: 0.18,
              reason: {
                clauses: [
                  {
                    kind: "pinned",
                    at: { start: monday("13:00"), end: monday("14:30") },
                    pinnedOn: "2026-02-08",
                  },
                  {
                    kind: "instead_of",
                    placement: { start: monday("09:00"), end: monday("10:30") },
                    objectiveDelta: 0.18,
                  },
                ],
              },
            }),
          ],
        }),
        pins: [buildPin()],
      }),
    );

    await userEvent.click(screen.getByLabelText(`${LEETCODE} · Career`));

    const detail = await screen.findByLabelText("Reason");
    expect(within(detail).getByText("pinned")).toBeInTheDocument();
    expect(
      within(detail).getByText("Mon 13:00 to 14:30 · you moved it here on Sun 08 Feb"),
    ).toBeInTheDocument();
    expect(within(detail).getByText("instead of")).toBeInTheDocument();
    expect(within(detail).getByText("cost")).toBeInTheDocument();
    expect(within(detail).getByText("+0.18 against the proposal")).toBeInTheDocument();
    expect(detail.querySelectorAll("p")).toHaveLength(0);
  });

  it("closes on Escape and clears the selection", async () => {
    await renderWeek(buildWeekView());
    await userEvent.click(screen.getByLabelText(`${LEETCODE} · Career`));
    await screen.findByLabelText("Detail");

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).not.toHaveAttribute("data-selected");
  });

  /* THE PANEL'S OWN CLOSE CONTROL, DRIVEN RATHER THAN READ. It writes the same open state the rail's control and `Enter`
   * write, and IN A BROWSER at this width it is the only control that offers the gesture, because the rail's column is
   * `display: none` above the threshold. jsdom applies no CSS, so the rail is in this render's DOM and would answer a
   * click: the query is scoped to the panel for that reason, and the width is what the case is about rather than what
   * it proves. It leaves the SELECTION alone, which is what separates it from `Escape`, and closing unmounts the control
   * that held focus, so focus falls to the body and `Enter` reaches the screen's own binding rather than a button's
   * activation. That reopen is asserted here because this is the width where the affordance is thinnest. */
  it("closes from the panel's own control, keeps the selection, and reopens with Enter", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX;
    await renderWeek(buildWeekView());
    await userEvent.keyboard("j");
    const detail = await screen.findByLabelText("Detail");

    await userEvent.click(within(detail).getByRole("button", { name: "Close the detail panel" }));

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
    expect(panelState()).toBe("closed");
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toHaveAttribute("data-selected");

    expect(document.body).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(await screen.findByLabelText("Detail")).toBeInTheDocument();
    expect(panelState()).toBe("open");
  });
});

describe("a pending proposal", () => {
  it("marks its target and raises no notification of any kind", async () => {
    await renderWeek(
      buildWeekView({
        proposal: buildProposal({ moved: [buildBlockChange({ blockId: BLOCK_LEETCODE })] }),
      }),
    );

    /* NO FILL AND A DASHED OUTLINE is the one state without a fill, assigned by the attribute in `block.css`. */
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toHaveAttribute("data-proposal");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("enables Approve only where there is something to approve", async () => {
    await renderWeek(buildWeekView({ proposal: null }));

    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
  });
});

describe("a conflict", () => {
  it("marks the block, raises a banner, and offers three answers with nothing moved", async () => {
    await renderWeek(buildWeekView({ conflicts: [buildConflict()] }));

    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toHaveAttribute("data-conflict");
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("A commitment landed on a planned block");
    expect(banner).toHaveTextContent("Nothing has been moved");
    for (const label of ["Move the block", "Keep both", "Retype the commitment"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("sends the answer the reader chose and nothing before they choose", async () => {
    await renderWeek(buildWeekView({ conflicts: [buildConflict()] }));
    const answered: unknown[] = [];
    apiServer.use(
      http.post(`${window.location.origin}/api/v1/conflicts/:id/resolve`, async ({ request }) => {
        answered.push(await request.json());
        return HttpResponse.json({ resolution: "kept-both" });
      }),
    );

    expect(answered).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Keep both" }));

    await waitFor(() => expect(answered).toEqual([{ resolution: "kept-both" }]));
  });

  it("offers the template path as well for a materialized template entry", async () => {
    await renderWeek(
      buildWeekView({
        conflicts: [
          buildConflict({
            binding: {
              kind: "template_entry",
              entityId: TASK_ID,
              occurrenceKey: "2026-02-09",
              splitIndex: null,
            },
          }),
        ],
      }),
    );

    expect(screen.getByRole("link", { name: "Edit the template" })).toHaveAttribute(
      "href",
      "/templates",
    );
    expect(screen.getByRole("button", { name: "Move the block" })).toBeInTheDocument();
  });
});

describe("the two controls in the band", () => {
  it("Re-solve dispatches immediately, whether or not a solve is already pending", async () => {
    await renderWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    const solves: string[] = [];
    apiServer.use(
      http.post(`${WEEK}/solve`, ({ request }) => {
        solves.push(new URL(request.url).search);
        return HttpResponse.json(buildOperation({ status: "pending" }), { status: 202 });
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Re-solve" }));

    await waitFor(() => expect(solves).toEqual(["?immediate=true"]));
  });

  /* THE ONE ROUTE THAT DEMANDS THE HEADER. Omitting `Idempotency-Key` on an approval is a 400 rather than a lost
   * guarantee, so it is asserted on the wire here as well as on the pin route. It is sent UNTYPED, because the api
   * reads it off the request object rather than declaring it as a parameter, so it is absent from the document every
   * generated client is built from: ticket 1134. */
  it("Shift+A approves the pending proposal, with the Idempotency-Key the route demands", async () => {
    await renderWeek(buildWeekView({ proposal: buildProposal() }));
    const keys: (string | null)[] = [];
    apiServer.use(
      http.post(`${WEEK}/approve`, ({ request }) => {
        keys.push(request.headers.get("Idempotency-Key"));
        return HttpResponse.json(
          {
            revisionId: "8c2d0e01-0000-4000-8000-000000000001",
            isoWeek: ISO_WEEK,
            reason: "user_approved",
            approvedAt: monday("09:00"),
            inputVersion: 6,
            solvedAgainstVersion: 4,
            adjustment: null,
            projection: buildOperation({ kind: "projection" }),
          },
          { status: 201 },
        );
      }),
    );

    await userEvent.keyboard("{Shift>}A{/Shift}");

    await waitFor(() => expect(keys).toHaveLength(1));
    expect(keys[0]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("states the plan currency as a word in the SCHEDULED cell's sub-line, and nowhere else", async () => {
    await renderWeek(buildWeekView({ operation: buildOperation({ status: "running" }) }));

    await waitFor(() => expect(screen.getByText("91 · solving")).toBeInTheDocument());
    /* ONE SURFACE STATES IT. Currency rides in that sub-line BECAUSE it qualifies the block count, so a second
     * surface stating the same word is the drift the rule exists to prevent: the band printed it too. The count is
     * asserted rather than the absence of one element, because `findByText` throws only on two matches of ONE text
     * node and the band's node read `91 blocks · solving · 12h visible`, which no query for either would see. */
    expect(screen.getAllByText(/solving/)).toHaveLength(1);
    /* NEVER A SPINNER, and the unpinned remainder is not degraded while a solve runs. */
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).not.toHaveAttribute("data-solving");
  });
});

describe("an empty slot's gutter label", () => {
  it("is drawn as a band even though the payload carries no label for it yet", async () => {
    await renderWeek(buildWeekView());

    /* The wire carries no rendered label for an empty slot yet (ticket 1350), so the band draws with an empty gutter
     * and there is nothing to activate: what the slot's Area and duration become is ticket 1490's. What is asserted
     * here is that the band is drawn AT ALL, because a gap left as nothing is pixel-identical to an ordinary gap. */
    expect(document.querySelectorAll(".week-band")).toHaveLength(2);
    expect(document.querySelectorAll(".week-band__label")).toHaveLength(1);
  });
});
