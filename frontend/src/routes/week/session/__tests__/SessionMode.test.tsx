/* THE WEEKLY SESSION AS A MODE, DRIVEN THROUGH THE REAL ROUTE AND THE REAL CLIENT.
 *
 * WHAT THIS FILE ANSWERS THAT A COMPONENT TEST CANNOT is whether the mode is reachable by URL at all: it is a search
 * parameter on the Week screen's own route, so nothing but rendering that route at that URL proves it survives a
 * reload. Every case here starts from a path rather than from a mounted component for that reason.
 *
 * THE HEADER MUST NOT BE SERIF, and the check is stated over the RENDERED ELEMENT rather than over a class name: a mode
 * draws no `h1` at all, because a page title is the one thing a mode may not claim. Asserting the absence of the heading
 * role is what makes that structural rather than a matter of which utility was reached for.
 *
 * THE SESSION HEADER'S FIGURES ARE THE PAYLOAD'S OWN SENTENCES. Every statement asserted here is composed server-side,
 * so a case that asserted its own wording would be asserting this test file's copy of the api's words. What is asserted
 * is that the sentence REACHES the screen, and the words are the fixture's.
 *
 * THE HEADER IS SENT ON A MUTATION MADE INSIDE THE MODE AND ON NOTHING ELSE, because only the caller knows whether the
 * weekly session is open: the recorder writes `session_mode_active` from what the caller states, so a client that sent
 * nothing would leave the early-catch metric's numerator structurally zero. Both directions are driven through the
 * real client rather than by reading the module's flag, because the flag is not the claim: the request is. */

import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../../testing/apiServer";
import { jsonHandler, pendingHandler } from "../../../../testing/apiStub";
import { renderAt } from "../../../../testing/renderRoute";
import { client } from "../../../../api/client";
import { SESSION_MODE_HEADER } from "../../../../api/sessionMode";
import {
  BLOCK_LEETCODE,
  EMPTY_WEEK_FACTS,
  GYM,
  ISO_WEEK,
  LEETCODE,
  PROMOTED_ENTRY_ID,
  SESSION_PATH,
  WEEK_PATH,
  buildAbsorbablePromotion,
  buildApproved,
  buildPinned,
  buildPromotionCandidate,
  buildProposal,
  buildRaisedItem,
  buildReadings,
  buildRetro,
  buildSession,
  buildShortfall,
  buildVerdict,
  buildWeekView,
  installSessionRead,
  installWeekReads,
  monday,
  wholeBandLine,
} from "../../__tests__/fixtures";

const APPROVED = buildApproved();
const SESSION_ROUTE = `${window.location.origin}/api/v1/reviews/week/:isoWeek`;

/* What an accept answers with, in the shape the api sends: four required fields, and the entry as the day-shape
 * routes render one. */
const ACCEPTED = {
  promotionId: `template_entry.${PROMOTED_ENTRY_ID}.2.780`,
  templateId: "9a1c5f2b-6d3e-4a7c-8b1f-0e2d4c6a8b3f",
  entry: {
    id: PROMOTED_ENTRY_ID,
    kind: "concrete",
    targetTime: "13:00:00",
    durationMinutes: 60,
    flexBandMinutes: 15,
    areaId: null,
    bindingTarget: "habit",
    bindingRef: "7f2b8c1d-4e5a-4b6c-9d8e-1a2b3c4d5e6f",
  },
  statement: "Your Weekday shape now places this at 13:00, where it was at 07:00.",
};

function openTheSession(
  session = buildSession(),
  week = buildWeekView({ verdict: buildVerdict(), proposal: buildProposal() }),
): void {
  installWeekReads(week);
  installSessionRead(session);
}

/**
 * A write route, recording the session-mode header each request carried.
 *
 * The header is where the caller's own answer crosses, so what a case asserts is the REQUEST rather than the module
 * flag behind it: a flag read correctly and never put on a request would leave the metric's numerator structurally
 * zero, which is the state ticket 1431 measured.
 */
function recordSessionHeaders(path: string, body: object): (string | null)[] {
  const stated: (string | null)[] = [];
  apiServer.use(
    http.post(`${window.location.origin}${path}`, ({ request }) => {
      stated.push(request.headers.get(SESSION_MODE_HEADER));
      return HttpResponse.json(body, { status: 200 });
    }),
  );
  return stated;
}

/** Selecting a block and nudging it fifteen minutes, which is the pin path the mode reuses. */
async function pinTheSelectedBlock(): Promise<void> {
  await userEvent.click(await screen.findByLabelText(`${LEETCODE} · Career`));
  await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");
}

/**
 * A write route, recording the path and the body of every request it answered.
 *
 * The PATH is what a promotion's two answers are stated over: neither takes a body, because every value a promotion
 * states is in its identifier. So a recorder that only kept bodies would have nothing to assert, and the case that
 * matters -- that the identifier the api sent is the identifier the client sends back -- is about the URL.
 *
 * The answer is a SHAPE THE API CAN SEND, so this fixture is not the thing its own sibling comment warns about.
 * Neither hook reads the response body -- both go through `apply`, which reads only the refusal -- so an empty
 * object would work; it would also be the one shape `PromotionAcceptedResponse` cannot be.
 */
function recordRequests(
  path: string,
  answer: object = ACCEPTED,
): {
  readonly paths: string[];
  readonly bodies: unknown[];
} {
  const paths: string[] = [];
  const bodies: unknown[] = [];
  apiServer.use(
    http.post(`${window.location.origin}${path}`, async ({ request }) => {
      paths.push(new URL(request.url).pathname);
      bodies.push(await request.json().catch(() => null));
      return HttpResponse.json(answer, { status: 200 });
    }),
  );
  return { paths, bodies };
}

/**
 * The table row that holds one binding, found through the cell that names it.
 *
 * The cell's accessible name is the title exactly, so no title is ever compiled as a pattern: a `(` or a `.` in one
 * would otherwise widen the lookup or throw.
 */
function rowHolding(title: string): HTMLElement {
  const row = screen.getByRole("cell", { name: title }).closest("tr");
  if (!(row instanceof HTMLElement)) throw new Error(`no row holds ${title}`);
  return row;
}

describe("the mode is reachable by URL and is not a destination", () => {
  it("renders the session at `?mode=session` on the week's own route", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByLabelText("Weekly session")).toBeInTheDocument();
  });

  it("survives a reload, because the mode is in the URL rather than in state", async () => {
    openTheSession();
    const first = renderAt(SESSION_PATH);
    expect(await screen.findByLabelText("Weekly session")).toBeInTheDocument();
    first.unmount();

    /* A fresh render at the same URL is what a reload is: no state carries over, and the mode still opens. */
    renderAt(SESSION_PATH);

    expect(await screen.findByLabelText("Weekly session")).toBeInTheDocument();
  });

  it("takes no serif page title, because a mode does not claim the type reserved for one", async () => {
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");

    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.getByText("Weekly session")).toBeInTheDocument();
  });

  it("draws no serif page title while its own payload is still in flight", async () => {
    /* A mode may not claim a destination's type, not even for the second the read takes. The screen's
     * band is serif, so the session's own pending state takes the MODE's header instead, which states
     * no range because the week has not been read. */
    installWeekReads(buildWeekView({ verdict: buildVerdict(), proposal: buildProposal() }));
    apiServer.use(pendingHandler(`/api/v1/reviews/week/${ISO_WEEK}`));
    renderAt(SESSION_PATH);

    expect(await screen.findByText("Reading this week's session")).toBeVisible();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
    expect(screen.getByText("Weekly session")).toBeInTheDocument();
  });

  it("says it is run on request and never asks for the reader", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/whenever you ask, and syncr never asks for you/)).toBeVisible();
  });

  it("leaves the session by a real link that keeps the week", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    const leaving = await screen.findByRole("link", { name: "Leave the session" });
    expect(leaving).toHaveAttribute("href", WEEK_PATH);
  });

  it("is not opened by the week screen's own URL", async () => {
    openTheSession();
    renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    expect(screen.queryByLabelText("Weekly session")).not.toBeInTheDocument();
  });

  it("is opened from the week screen's own band, by a real link carrying the week", async () => {
    /* THE CRITERION IS "triggered manually", and a mode with no control in the product is a mode only a pasted URL can
     * open. The closest sibling sets the shape: the pie review is the same kind of mode and `AreaBand` carries its own
     * `Run the pie review` link. A real link rather than a handler, so middle-click and cmd-click work. */
    openTheSession();
    renderAt(WEEK_PATH);

    const opening = await screen.findByRole("link", { name: "Run the weekly session" });
    expect(opening).toHaveAttribute("href", SESSION_PATH);
  });

  it("offers no such link inside the session, because the reader is already in it", async () => {
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");

    expect(screen.queryByRole("link", { name: "Run the weekly session" })).not.toBeInTheDocument();
  });

  it("lands on the screen for a mode this build does not have", async () => {
    openTheSession();
    renderAt(`/week?week=${ISO_WEEK}&mode=weekly`);

    expect(await screen.findByLabelText(`${LEETCODE} · Career`)).toBeInTheDocument();
    expect(screen.queryByLabelText("Weekly session")).not.toBeInTheDocument();
  });
});

describe("what the session raises", () => {
  it("renders every category with the api's own sentence", async () => {
    const raised = [
      buildRaisedItem(),
      buildRaisedItem({
        key: "habit_at_debt_cap:gym",
        kind: "habit_at_debt_cap",
        title: GYM,
        statement: "Two sessions behind, capped at six.",
      }),
      buildRaisedItem({
        key: "repeated_collision:task",
        kind: "repeated_collision",
        title: "Standup",
        statement: "Standup has landed on this block in 4 weeks. Stated rather than acted on.",
      }),
      buildRaisedItem({
        key: "overdue_task:leetcode",
        kind: "overdue_task",
        title: LEETCODE,
        statement: "Overdue: it was due 3 Feb and 1h of it is left.",
      }),
      buildRaisedItem({
        key: "at_risk_task:leetcode",
        kind: "at_risk_task",
        title: LEETCODE,
        statement: "At risk: the week cannot fit the work this task needs before its deadline.",
      }),
      buildRaisedItem({
        key: "floor_at_risk:career",
        kind: "floor_at_risk",
        title: "Career",
        statement: "1h30m short of the floor this week reserves.",
      }),
      buildRaisedItem({
        key: "new_anchor:standup",
        kind: "new_anchor",
        title: "Standup",
        statement: "New commitment, Tue 10 Feb 09:00 for 30m. It is immovable.",
      }),
      buildRaisedItem({
        key: "cadence_due:gym",
        kind: "cadence_due",
        title: GYM,
        statement: "3 occurrences due in this week's plan.",
      }),
    ];
    openTheSession(buildSession({ raised }));
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    for (const item of raised) {
      expect(screen.getByText(item.statement)).toBeInTheDocument();
    }
  });

  it("gives each category the eyebrow this screen labels it with", async () => {
    openTheSession(
      buildSession({
        raised: [
          buildRaisedItem(),
          buildRaisedItem({ key: "floor_at_risk:career", kind: "floor_at_risk", title: "Career" }),
        ],
      }),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    expect(screen.getByText("Chronically skipped")).toBeInTheDocument();
    expect(screen.getByText("Floor at risk")).toBeInTheDocument();
  });

  it("groups two items of one category under one eyebrow", async () => {
    openTheSession(
      buildSession({
        raised: [
          buildRaisedItem(),
          buildRaisedItem({ key: "chronic_skip:habit:reading", title: "Reading" }),
        ],
      }),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    expect(screen.getAllByText("Chronically skipped")).toHaveLength(1);
    expect(screen.getByText(GYM)).toBeInTheDocument();
    expect(screen.getByText("Reading")).toBeInTheDocument();
  });

  it("says nothing is outstanding, and NOT in amber", async () => {
    /* Amber means "needs attention", so painting the absence of a raise with it would spend the
     * pigment on nothing. The sentence is still worth saying: it is the most useful thing the session
     * can tell a reader who has been keeping up. */
    openTheSession(buildSession({ raised: [] }));
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/Nothing is outstanding/)).toBeVisible();
    const raised = screen.getByLabelText("Raised in this session");
    expect(raised.className).not.toContain("notice--amber");
  });

  it("renders the raised panel at amber panel volume", async () => {
    openTheSession();
    const { container } = renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    const panel = container.querySelector(".notice--panel.notice--amber");
    expect(panel).not.toBeNull();
  });
});

describe("the raises that appear in this mode only", () => {
  it("shows no chronic skip and no promotion on the week screen itself", async () => {
    openTheSession();
    renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    expect(screen.queryByLabelText("Raised in this session")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Repeated pins")).not.toBeInTheDocument();
  });
});

describe("the retrospective half", () => {
  it("states the confirmed and unconfirmed day counts of its own period", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/5 confirmed days and 1 unconfirmed/)).toBeVisible();
  });

  it("reports off-plan days separately from unconfirmed ones", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/1 declared off-plan/)).toBeVisible();
  });

  /* THE BAND'S FIGURE AND THE RETROSPECTIVE'S ARE DIFFERENT PERIODS, and they arrive in different payloads: the band
   * counts the unanswered days of the week being PLANNED and the retrospective reports the week under REVIEW. A mode
   * drawing one from the other would report the reviewed week's figure on the week being planned. */
  it("keeps the band's count of this week apart from the reviewed week's", async () => {
    const thisWeek = 5;
    const retro = buildRetro();
    expect(retro.days.unconfirmed, "the reviewed week must disagree with this one").not.toBe(
      thisWeek,
    );
    const readings = buildReadings({ unconfirmedDays: thisWeek });
    openTheSession(buildSession({ retro }), buildWeekView({ readings }));
    renderAt(SESSION_PATH);

    expect((await screen.findByText(/blocks ·/)).textContent).toBe(
      wholeBandLine(readings.blockCount, `${thisWeek} days unconfirmed`),
    );
    expect(await screen.findByText(/5 confirmed days and 1 unconfirmed/)).toBeVisible();
  });

  it("reports a period with no confirmed day rather than charting nothing", async () => {
    openTheSession(
      buildSession({
        retro: buildRetro({
          days: { confirmed: 0, unconfirmed: 7, offPlan: 0, statement: null },
          statement:
            "No day of this period was answered for: 7 hold blocks nobody has confirmed. " +
            "Nothing below is measured behaviour, so there is nothing to chart until a day is " +
            "confirmed on Today.",
        }),
      }),
    );
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/No day of this period was answered for/)).toBeVisible();
  });

  it("names the week under review, which is the one before the week planned", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText("Last week · 2026-W06")).toBeInTheDocument();
  });

  it("says a week with no plan of record has no target to compare against", async () => {
    openTheSession(
      buildSession({
        retro: buildRetro({
          discretionaryMinutes: null,
          categories: [
            {
              areaId: "3f6b2c9d-1a77-4a1b-9a5f-8a2e4a1b9a5f",
              targetMinutes: null,
              actualMinutes: 0,
            },
          ],
        }),
      }),
    );
    renderAt(SESSION_PATH);

    expect(await screen.findByText("Last week has no target to compare against")).toBeVisible();
  });
});

describe("the promotion candidates", () => {
  it("names the binding, the time, and the week count", async () => {
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    expect(screen.getByRole("cell", { name: LEETCODE })).toBeInTheDocument();
    expect(screen.getByText("Tue 13:00")).toBeInTheDocument();
    expect(screen.getByText("4 weeks")).toBeInTheDocument();
  });

  it("renders at amber panel volume, which is the row the notice table gives it", async () => {
    openTheSession();
    const { container } = renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    const panel = container.querySelector('[aria-label="Repeated pins"]');
    expect(panel?.className).toContain("notice--panel");
    expect(panel?.className).toContain("notice--amber");
  });

  it("renders nothing at all when no promotion is available", async () => {
    /* The notice table's row is "promotion AVAILABLE", so an amber surface saying nothing has been pinned three weeks
     * running would spend a notice pigment on the absence of a notice. */
    openTheSession(buildSession({ promotions: [] }));
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    expect(screen.queryByLabelText("Repeated pins")).not.toBeInTheDocument();
  });

  it("states that nothing is applied without acceptance", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/only when you accept it/)).toBeVisible();
  });

  it("offers both answers on a pattern the template can absorb, and sends the api's own identifier", async () => {
    /* THE REQUEST IS THE CLAIM, and the identifier is the api's. Nothing stores a candidate, so the id is derived at
     * both ends: the payload renders the group the rule found and the route parses it back. A panel that composed its
     * own key out of three fields would send one the route cannot read, which is what this asserts it does not. */
    const candidate = buildAbsorbablePromotion();
    openTheSession(buildSession({ promotions: [candidate] }));
    const accepted = recordRequests(`/api/v1/promotions/${candidate.id}/accept`);
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    await userEvent.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() =>
      expect(accepted.paths).toEqual([`/api/v1/promotions/${candidate.id}/accept`]),
    );
    /* No body at all: every value a promotion states is in its identifier, so a body would be a second place to
     * send the same four values. */
    expect(accepted.bodies).toEqual([null]);
  });

  it("declines through the decline route, and sends no body either", async () => {
    const candidate = buildAbsorbablePromotion();
    openTheSession(buildSession({ promotions: [candidate] }));
    const declined = recordRequests(`/api/v1/promotions/${candidate.id}/decline`);
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    await userEvent.click(screen.getByRole("button", { name: "Decline" }));

    await waitFor(() =>
      expect(declined.paths).toEqual([`/api/v1/promotions/${candidate.id}/decline`]),
    );
    expect(declined.bodies).toEqual([null]);
  });

  it("draws no accept control for a pattern the template cannot absorb, and states why", async () => {
    /* A promotion MOVES a day-shape entry, so content no entry holds has nothing to move. The api sends the reason
     * with the candidate, and the panel renders it in place of the control: the reader meets the limit where it is
     * rather than by pressing a button that refuses. The DECLINE is still offered, because the answer it records is
     * about the asking rather than about the template. */
    const candidate = buildPromotionCandidate();
    openTheSession(buildSession({ promotions: [candidate] }));
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Decline" })).toBeInTheDocument();
    expect(screen.getByText(candidate.acceptRefusal ?? "")).toBeVisible();
  });

  it("draws the accept control in the absorbable row alone, in a panel holding one of each", async () => {
    /* WHAT A SINGLE REFUSED CANDIDATE CANNOT SHOW. Where the panel holds one refused row, "no accept control for
     * this row" and "no accept control anywhere" are one reading, and a panel that had lost the control altogether
     * satisfies it too. A pair separates them: the control is asserted in the row it belongs to rather than counted
     * over the table, and the DECLINE in both rows, because the answer a decline records is about the asking rather
     * than the template. */
    const refused = buildPromotionCandidate();
    const refusal = refused.acceptRefusal;
    if (refusal === null) throw new Error("the refused candidate carries no sentence");
    openTheSession(buildSession({ promotions: [buildAbsorbablePromotion(), refused] }));
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    /* The row is found through its binding cell rather than through a pattern built from the title. */
    const absorbableRow = rowHolding(GYM);
    const refusedRow = rowHolding(LEETCODE);

    expect(within(absorbableRow).getByRole("button", { name: "Accept" })).toBeVisible();
    expect(within(refusedRow).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    expect(within(refusedRow).getByText(refusal)).toBeVisible();
    expect(within(absorbableRow).getByRole("button", { name: "Decline" })).toBeVisible();
    expect(within(refusedRow).getByRole("button", { name: "Decline" })).toBeVisible();
  });

  it("renders the api's sentence when an answer is refused", async () => {
    /* The 409 a raced accept meets: the entry was removed between the read and the press. The api's own sentence is
     * rendered rather than paraphrased, because it states what was not changed. */
    const candidate = buildAbsorbablePromotion();
    openTheSession(buildSession({ promotions: [candidate] }));
    apiServer.use(
      http.post(`${window.location.origin}/api/v1/promotions/${candidate.id}/accept`, () =>
        HttpResponse.json(
          {
            type: "syncr:conflict",
            title: "Conflict",
            status: 409,
            detail: "The day-shape entry this pattern is about is no longer declared.",
          },
          { status: 409, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    await userEvent.click(screen.getByRole("button", { name: "Accept" }));

    expect(await screen.findByText(/no longer declared/)).toBeVisible();
  });

  it("carries the session header on an answer, because it is a mutation made in the mode", async () => {
    /* The caller's own answer again, on the two writes this ticket adds: the middleware is on the client, so
     * a hook added later inherits it, and this is the case that would notice if these two had been given
     * their own call path. */
    const candidate = buildAbsorbablePromotion();
    openTheSession(buildSession({ promotions: [candidate] }));
    const stated = recordSessionHeaders(`/api/v1/promotions/${candidate.id}/decline`, {
      promotionId: candidate.id,
      declinedAt: "2026-02-16T09:00:00+00:00",
      suppressedUntil: "2026-05-18T09:00:00+00:00",
      suppressionWeeks: 13,
      statement: "Nothing was changed in your templates.",
    });
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    await userEvent.click(screen.getByRole("button", { name: "Decline" }));

    await waitFor(() => expect(stated).toEqual(["true"]));
  });

  it("renders the name the api resolved, including its fallback, and holds none of its own", async () => {
    /* THE FALLBACK IS THE API'S. A repeated collision's block needs the same answer for the same
     * reason, so one absence has one spelling: the reader's word for the kind, not the wire's token.
     * A client that kept its own would have rendered `anchor_prep` verbatim. */
    openTheSession(
      buildSession({
        promotions: [buildPromotionCandidate({ title: "a habit" })],
      }),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Repeated pins");

    expect(screen.getByRole("cell", { name: "a habit" })).toBeInTheDocument();
  });
});

describe("a week that moved on while the session was open", () => {
  it("says the raises are older than the plan beside them", async () => {
    /* WHAT `inputVersion` IS FOR. A pin made inside the session bumps the week, and the plan and the verdict re-read on
     * the spot while the raises do not: the reader is told which half is older rather than left to assume both are
     * current. The pair below is what a pin produces, one version apart. */
    openTheSession(buildSession({ inputVersion: 3 }));
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/newer than the list below/)).toBeVisible();
  });

  it("says nothing while the two readings name one version", async () => {
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Raised in this session");

    expect(screen.queryByText(/newer than the list below/)).not.toBeInTheDocument();
  });
});

describe("the detail panel the keyboard map opens", () => {
  it("opens inside the mode, so Enter is not a key that does nothing", async () => {
    /* The mode inherits the whole keyboard map, and `Enter` opens the detail panel. A surface that took the binding and
     * drew no panel would leave a key that silently sets state nothing renders.
     *
     * FOCUS IS TAKEN OFF THE BLOCK BEFORE `Enter`, because a selected block holds focus and a block is a real button:
     * `Enter` on it is the button's own activation, which opens the panel through the pointer's handler and would leave
     * this case green with the binding deleted. Off the block, the document binding is the only thing that can answer. */
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    await userEvent.keyboard("j");
    screen.getByLabelText(`${LEETCODE} · Career`).blur();
    expect(document.body).toHaveFocus();
    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();

    await userEvent.keyboard("{Enter}");

    expect(await screen.findByRole("button", { name: "Close the detail panel" })).toBeVisible();
  });
});

describe("the verdict and the one approve action", () => {
  it("renders the verdict panel from the week's own reading", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByLabelText("Verdict")).toBeInTheDocument();
  });

  it("reflows the verdict live from the pin the reader made inside the mode", async () => {
    /* EDITING INSIDE THE SESSION PINS, and the verdict the pin answers with replaces the one on screen without a second
     * read: the panel is the screen's own and it reads the pin's live verdict first. That is what "the verdict updates
     * live" means, and it is the reason the mode reuses the panel rather than drawing one from its own payload. */
    openTheSession();
    apiServer.use(
      http.post(`${window.location.origin}/api/v1/weeks/${ISO_WEEK}/pins`, () =>
        HttpResponse.json(
          buildPinned({
            verdict: buildVerdict({
              inputVersion: 9,
              shortfalls: [buildShortfall({ against: ["The reading the pin produced"] })],
              tradeoffs: [],
            }),
          }),
          { status: 201 },
        ),
      ),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Verdict");

    await pinTheSelectedBlock();

    expect(await screen.findByText("The reading the pin produced")).toBeInTheDocument();
  });

  it("never opens on a plan-less week, because the screen's own empty state answers first", async () => {
    /* THE PAIR THE PREVIOUS VERSION OF THIS CASE COMPOSED CANNOT EXIST. `WeeklySessionResponse.verdict` is null exactly
     * when the planned week holds no plan, and `useWeekScreen` answers `empty` on exactly that condition, so a week view
     * with a live plan beside a session with a null verdict is not a state the server can produce. What the reader gets
     * is the empty state, which names the reason and carries the two actions that fix it: the mode is a branch of the
     * READY screen, and there is no second sentence on the payload claiming otherwise. */
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: EMPTY_WEEK_FACTS,
      }),
    );
    installSessionRead(buildSession({ verdict: null }));
    renderAt(SESSION_PATH);

    expect(await screen.findByText("This week is beyond your planning horizon")).toBeVisible();
    expect(screen.queryByLabelText("Weekly session")).not.toBeInTheDocument();
  });

  it("commits the week through the approve endpoint the screen already uses", async () => {
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/approve`, APPROVED);
    renderAt(SESSION_PATH);

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));

    await waitFor(() => {
      expect(stated).toHaveLength(1);
    });
  });
});

describe("VE3: the session mode header, and the mutations that carry it", () => {
  it("states that a session is open on a pin made inside the mode", async () => {
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/pins`, buildPinned());
    renderAt(SESSION_PATH);

    await pinTheSelectedBlock();

    await waitFor(() => {
      expect(stated).toEqual(["true"]);
    });
  });

  it("sends no header at all on a pin made outside the mode", async () => {
    /* Absent rather than `false`: the api reads an absent header as false, and two spellings of one statement is how a
     * call site comes to send the wrong one. */
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/pins`, buildPinned());
    renderAt(WEEK_PATH);

    await pinTheSelectedBlock();

    await waitFor(() => {
      expect(stated).toEqual([null]);
    });
  });

  it("states it on the approval as well, which is a second write with no header of its own", async () => {
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/approve`, APPROVED);
    renderAt(SESSION_PATH);

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));

    await waitFor(() => {
      expect(stated).toEqual(["true"]);
    });
  });

  it("sends no header on the session's own READ, which has no use for one", async () => {
    /* The api resolves the header only where a verdict is recorded, because its refusal for an unreadable value says
     * nothing was changed -- which is true of a mutation and meaningless on a read. */
    installWeekReads(buildWeekView());
    const stated: (string | null)[] = [];
    apiServer.use(
      http.get(SESSION_ROUTE, ({ request }) => {
        stated.push(request.headers.get(SESSION_MODE_HEADER));
        return HttpResponse.json(buildSession());
      }),
    );
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");

    expect(stated).toEqual([null]);
  });

  it("stops stating it once the reader leaves the session", async () => {
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/pins`, buildPinned());
    const inSession = renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");
    inSession.unmount();

    renderAt(WEEK_PATH);
    await pinTheSelectedBlock();

    await waitFor(() => {
      expect(stated).toEqual([null]);
    });
  });

  it("stops stating it when the reader leaves the week screen entirely", async () => {
    /* THE CASE THE PREVIOUS ONE CANNOT REACH. Coming back to the week screen re-runs the mode's own declaration with
     * `false`, so that case would pass with no cleanup at all. Navigating to ANOTHER screen unmounts the route and runs
     * nothing: without the effect's teardown the flag stays true, and the next mutation the reader makes anywhere in the
     * product would claim a session that is not open. The write is issued through the real client rather than a screen,
     * because the claim is about the middleware and not about any one surface. */
    openTheSession();
    const stated = recordSessionHeaders(`/api/v1/weeks/${ISO_WEEK}/pins`, buildPinned());
    const inSession = renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");
    inSession.unmount();

    await client.POST("/api/v1/weeks/{iso_week}/pins", {
      params: { path: { iso_week: ISO_WEEK } },
      body: { blockId: BLOCK_LEETCODE, start: monday("09:15") },
    });

    expect(stated).toEqual([null]);
  });
});

describe("the session's own read", () => {
  it("is not made at all on the week screen, because the mode is what pays for it", async () => {
    installWeekReads(buildWeekView());
    const asked = recordSessionReads();
    renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    expect(asked).toEqual([]);
  });

  it("names the week the URL asked for", async () => {
    installWeekReads(buildWeekView());
    const asked = recordSessionReads();
    renderAt(SESSION_PATH);
    await screen.findByLabelText("Weekly session");

    expect(asked).toEqual([ISO_WEEK]);
  });

  it("says which read failed rather than rendering the screen", async () => {
    installWeekReads(buildWeekView());
    apiServer.use(
      jsonHandler(`/api/v1/reviews/week/${ISO_WEEK}`, {
        status: 503,
        body: {
          type: "https://syncr.local/problems/unexpected",
          title: "Unavailable",
          status: 503,
          detail: "The session could not be assembled.",
        },
      }),
    );
    renderAt(SESSION_PATH);

    expect(await screen.findByText("The session was not read")).toBeInTheDocument();
    expect(screen.getByText("The session could not be assembled.")).toBeInTheDocument();
  });
});

/** Every week the session's own read asked for, in order. */
function recordSessionReads(): string[] {
  const asked: string[] = [];
  apiServer.use(
    http.get(SESSION_ROUTE, ({ params }) => {
      asked.push(String(params.isoWeek));
      return HttpResponse.json(buildSession());
    }),
  );
  return asked;
}
