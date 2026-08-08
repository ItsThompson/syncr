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
 * THE HEADER IS SENT ON A MUTATION MADE INSIDE THE MODE AND ON NOTHING ELSE, which is `VE3` end to end from this side:
 * the recorder writes `session_mode_active` from what the caller states, so a client that sent nothing would leave the
 * early-catch metric's numerator structurally zero. Both directions are driven through the real client rather than by
 * reading the module's flag, because the flag is not the claim: the request is. */

import { screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../../testing/apiServer";
import { jsonHandler } from "../../../../testing/apiStub";
import { renderAt } from "../../../../testing/renderRoute";
import { client } from "../../../../api/client";
import { SESSION_MODE_HEADER } from "../../../../api/sessionMode";
import {
  BLOCK_LEETCODE,
  GYM,
  ISO_WEEK,
  LEETCODE,
  SESSION_PATH,
  WEEK_PATH,
  buildApproved,
  buildPinned,
  buildPromotionCandidate,
  buildProposal,
  buildRaisedItem,
  buildRetro,
  buildSession,
  buildShortfall,
  buildVerdict,
  buildWeekView,
  installSessionRead,
  installWeekReads,
  monday,
} from "../../__tests__/fixtures";

const APPROVED = buildApproved();
const SESSION_ROUTE = `${window.location.origin}/api/v1/reviews/week/:isoWeek`;

function openTheSession(session = buildSession()): void {
  installWeekReads(buildWeekView({ verdict: buildVerdict(), proposal: buildProposal() }));
  installSessionRead(session);
}

/**
 * A write route, recording the session-mode header each request carried.
 *
 * The header is what `VE3` is stated over, so what a case asserts is the REQUEST rather than the module flag behind it:
 * a flag read correctly and never put on a request would leave the metric's numerator structurally zero, which is the
 * state ticket 1431 measured.
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
        weeks: null,
      }),
      buildRaisedItem({
        key: "repeated_collision:task",
        kind: "repeated_collision",
        title: "Standup",
        statement: "Standup has landed on this block in 4 weeks. Stated rather than acted on.",
        weeks: 4,
      }),
      buildRaisedItem({
        key: "overdue_task:leetcode",
        kind: "overdue_task",
        title: LEETCODE,
        statement: "Overdue: it was due 3 Feb and 1h of it is left.",
        weeks: null,
      }),
      buildRaisedItem({
        key: "at_risk_task:leetcode",
        kind: "at_risk_task",
        title: LEETCODE,
        statement: "At risk: the week cannot fit the work this task needs before its deadline.",
        weeks: null,
      }),
      buildRaisedItem({
        key: "floor_at_risk:career",
        kind: "floor_at_risk",
        title: "Career",
        statement: "1h30m short of the floor this week reserves.",
        weeks: null,
      }),
      buildRaisedItem({
        key: "new_anchor:standup",
        kind: "new_anchor",
        title: "Standup",
        statement: "New commitment, Tue 10 Feb 09:00 for 30m. It is immovable.",
        weeks: null,
      }),
      buildRaisedItem({
        key: "cadence_due:gym",
        kind: "cadence_due",
        title: GYM,
        statement: "3 occurrences due in this week's plan.",
        weeks: null,
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

  it("says nothing is outstanding rather than rendering an empty panel", async () => {
    openTheSession(buildSession({ raised: [] }));
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/Nothing is outstanding/)).toBeVisible();
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
    expect(screen.queryByText("Repeated pins")).not.toBeInTheDocument();
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
    await screen.findByText("Repeated pins");

    expect(screen.getByText(`${LEETCODE}`)).toBeInTheDocument();
    expect(screen.getByText("Tue 13:00")).toBeInTheDocument();
    expect(screen.getByText("4 weeks")).toBeInTheDocument();
  });

  it("states that nothing is applied without acceptance", async () => {
    openTheSession();
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/only when you accept it/)).toBeVisible();
  });

  it("offers no accept and no decline, because neither route exists in this build", async () => {
    openTheSession();
    renderAt(SESSION_PATH);
    await screen.findByText("Repeated pins");

    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /decline/i })).not.toBeInTheDocument();
  });

  it("falls back to the candidate's kind for content the planned week no longer holds", async () => {
    openTheSession(
      buildSession({
        promotions: [buildPromotionCandidate({ entityId: "11111111-1111-4111-8111-111111111111" })],
      }),
    );
    renderAt(SESSION_PATH);
    await screen.findByText("Repeated pins");

    expect(screen.getByText("task")).toBeInTheDocument();
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

  it("says why a week with no plan has no verdict", async () => {
    openTheSession(
      buildSession({
        verdict: null,
        statement:
          "The week you are planning holds no plan yet, so it has no verdict and nothing is due " +
          "in it. Solve the week, and the raises about it appear beside the retrospective below.",
      }),
    );
    renderAt(SESSION_PATH);

    expect(await screen.findByText(/holds no plan yet/)).toBeVisible();
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
