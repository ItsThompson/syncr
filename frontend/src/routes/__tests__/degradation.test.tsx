/* THE DEGRADATION NOTICES, EACH AT THE VOLUME AND PIGMENT ITS CASE IS ASSIGNED, NAMING WHAT SURVIVES IT.
 *
 * The rows of section 19's matrix that are NOT a screen drawing a surface: a solve that produced no plan, a
 * refused pin, a refused confirmation, a proposal that was replaced, a projection that stopped, a write target
 * whose token expired, and a feed that can no longer be read. Each is a notice, and what has to be true of a
 * notice is four things a rendering can be asked about:
 *
 *   VOLUME IS POSITION. Inline at the row it concerns, a panel at the head of the screen, a banner in the top
 *   bar until the condition clears. There is no fourth: syncr never blocks a reader over a degradation.
 *   PIGMENT IS KIND. Informational spends no signal pigment, amber needs attention with nothing broken, oxide is
 *   a failure, verdigris is a confirmation.
 *   EVERY NOTICE NAMES WHAT STILL WORKS. A notice that says only what broke leaves a reader unable to decide what
 *   to do next, which is the whole reason the type refuses an empty list.
 *   THE DEGRADED STATE MUST NOT RENDER AS THE HEALTHY ONE. A stale feed's commitments are retained, so a day
 *   holding them looks exactly as it did while the feed answered. That is what the inline notice is for.
 *
 * ONLY CONFLICTS NOTIFY, and the sweep at the foot of this file is over the stream's own event union rather than
 * over a list of the four: a fifth event type reaches that sweep the day it is declared. */

import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  calendarSources,
  eventStream,
  googleConnection,
  jsonHandler,
  recordingHandler,
} from "../../testing/apiStub";
import { indicatorsIn } from "../../testing/indicators";
import { renderAt } from "../../testing/renderRoute";
import { EVENT_TYPES, type EventType } from "../../api/events";
import { buildAreas as buildTodayAreas, buildDay } from "../today/__tests__/fixtures";
import { hostSpan, hostToday, stubDay } from "../today/__tests__/render";
import { buildSource, buildSyncState } from "../settings/__tests__/fixtures";
import {
  BLOCK_LEETCODE,
  ISO_WEEK,
  LEETCODE,
  WEEK_PATH,
  buildConflict,
  buildOperation,
  buildProposal,
  buildWeekView,
  installWeekReads,
} from "../week/__tests__/fixtures";

/** The resource whose read composes the two oxide banners, which is where their words are written. */
const CONNECTION_PATH = "/api/v1/calendar-sources/google/connection";

/** An instant some hours before the host's now. The staleness threshold itself lives on the api. */
const staleSince = (hours: number) => new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();

/** A day holding an imported commitment, which is what makes it a day a feed's outage can have touched. */
function dayWithAnAnchor() {
  return buildDay({
    date: hostToday(),
    span: hostSpan(),
    behind: [],
    ahead: [
      {
        blockId: BLOCK_LEETCODE,
        interval: {
          start: `${hostToday()}T13:30:00+00:00`,
          end: `${hostToday()}T15:00:00+00:00`,
        },
        durationMinutes: 90,
        areaId: null,
        areaName: null,
        title: "Lecture · Signals",
        origin: "anchor",
        outcome: null,
      },
    ],
    blockCount: 1,
    presumedCount: 0,
  });
}

function noticeSurfaces(container: ParentNode, pigment: string): Element[] {
  return [...container.querySelectorAll(`.notice--${pigment}`)];
}

describe("a solve that produced no plan", () => {
  it("states it at panel volume in oxide, with the attempt count, over the plan it did not replace", async () => {
    const stream = eventStream();
    installWeekReads(buildWeekView({ operation: buildOperation({ status: "running" }) }));
    apiServer.use(stream.handler);
    const { container } = renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    stream.push(
      "operation",
      buildOperation({
        status: "failed",
        attempt: 3,
        statement:
          "This work could not complete. The previous plan for the week is untouched and still projected.",
        error: { code: "solver_timeout", message: "no plan within the budget" },
      }),
    );

    /* THE PANEL, AND THE COUNT IN IT. Retries here are bounded and a `failed` status reaching a client has spent
     * every attempt it was given, so the count is what separates bad luck from a week that cannot be solved. */
    const panel = await waitFor(() => {
      const found = noticeSurfaces(container, "oxide").filter((one) =>
        one.className.includes("notice--panel"),
      );
      expect(found).toHaveLength(1);
      return found[0];
    });

    expect(panel.textContent).toContain("This week's solve produced no plan");
    expect(panel.textContent).toContain("attempted 3 times");
    expect(panel.textContent).toContain("still works · the plan on the grid");
    /* THE PREVIOUS PLAN IS STILL RENDERED AND STILL PROJECTED, which is the failure table's own promise: the
     * panel appears beside the plan rather than in place of it. */
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toBeInTheDocument();
    expect(screen.getByText(/stale/)).toBeInTheDocument();
    expect(indicatorsIn(container)).toEqual([]);
  });
});

describe("a write the api refused", () => {
  it("states a replaced proposal in the api's own words, and leaves the week on screen", async () => {
    installWeekReads(buildWeekView({ proposal: buildProposal() }));
    apiServer.use(
      recordingHandler("post", `/api/v1/weeks/${ISO_WEEK}/approve`, {
        status: 409,
        body: {
          type: "syncr:proposal-replaced",
          title: "This proposal has been replaced",
          status: 409,
          detail:
            "A newer proposal replaced the one you approved, so nothing was applied. Refresh to read it.",
        },
      }).handler,
    );
    const { container } = renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);

    (await screen.findByRole("button", { name: /Approve/ })).click();

    const panel = await waitFor(() => {
      const found = noticeSurfaces(container, "amber").filter((one) =>
        one.className.includes("notice--panel"),
      );
      expect(found.length).toBeGreaterThan(0);
      return found[0];
    });

    expect(panel.textContent).toContain("This proposal has been replaced");
    expect(panel.textContent).toContain("nothing was applied");
    expect(screen.getByLabelText(`${LEETCODE} · Career`)).toBeInTheDocument();
    expect(indicatorsIn(container)).toEqual([]);
  });
});

describe("a feed that can no longer be read", () => {
  /* THE NOTICE IS THE API'S OWN, arrived on the source list. Its sync state is deliberately FRESH: a surface that
   * computed staleness from the row would stay silent, so rendering the notice at all is the proof it renders
   * what the api composed. The days in doubt are named in the notice's scope, which is how a day marks itself
   * without computing anything. */
  const feedPanel = (dates: string[]) => [
    {
      id: `calendar.feed-stale.${failing.id}`,
      volume: "panel",
      pigment: "amber",
      title: "Uni timetable could not be read",
      detail:
        "The feed did not answer. It last answered a day ago. The commitments this feed already contributed " +
        "are retained and marked possibly stale rather than removed, so nothing disappears from a day you have " +
        "already planned.",
      unavailable: ["Reading new commitments from Uni timetable"],
      stillWorks: [
        "The commitments this feed already contributed, which are retained and marked possibly stale",
        "Solving the week, which still plans around every commitment already read",
      ],
      since: staleSince(30),
      action: null,
      scope: { screen: "settings", sourceId: failing.id, dates },
    },
  ];

  const failing = buildSource({
    displayName: "Uni timetable",
    state: "error",
    syncState: buildSyncState({
      lastSuccessAt: staleSince(1),
      lastAttemptAt: staleSince(1),
      lastError: null,
    }),
  });

  const sourcesRead = (notices: unknown[] = []) =>
    jsonHandler("/api/v1/calendar-sources", {
      status: 200,
      body: { sources: [failing], notices },
    });

  it("marks the day the api named as in doubt, in amber, with the api's own words", async () => {
    stubDay(dayWithAnAnchor(), buildTodayAreas());
    apiServer.use(sourcesRead(feedPanel([hostToday()])));
    const { container } = renderAt("/today");

    const inline = await waitFor(() => {
      const found = noticeSurfaces(container, "amber");
      expect(found).toHaveLength(1);
      return found[0];
    });

    expect(inline.className).toContain("notice--inline");
    expect(inline.textContent).toContain("Uni timetable could not be read");
    expect(inline.textContent).toContain("marked possibly stale rather than removed");
    expect(inline.textContent).toContain(
      "still works · The commitments this feed already contributed",
    );
    /* WHEN IT LAST ANSWERED, as a wall reading in the day's own zone rather than an instant a reader has to
     * convert. */
    expect(inline.textContent).toMatch(/since \d{4}-\d{2}-\d{2}/);
  });

  it("says nothing on a day the api did not name, which the outage cannot have touched", async () => {
    stubDay(dayWithAnAnchor(), buildTodayAreas());
    apiServer.use(sourcesRead(feedPanel(["2036-01-01"])));
    const { container } = renderAt("/today");

    await screen.findByText("Lecture · Signals");
    expect(noticeSurfaces(container, "amber")).toEqual([]);
  });

  it("says nothing while the api composes no notice, so the notice tracks the condition", async () => {
    stubDay(dayWithAnAnchor(), buildTodayAreas());
    apiServer.use(calendarSources({ status: 200, body: { sources: [buildSource()] } }));
    const { container } = renderAt("/today");

    await screen.findByText("Lecture · Signals");
    expect(noticeSurfaces(container, "amber")).toEqual([]);
  });

  /* THE READ DEGRADES TO SILENCE RATHER THAN TO A FAILURE SURFACE, which is the promise `useTodayLedger` makes in
   * prose: the ledger's whole job is answering for blocks, and a source list that did not arrive must not take the
   * rows off the screen. The matrix sweep refuses every read at once, so it cannot tell this arm from the day's
   * own; this is the one case that can. */
  it("keeps the ledger on screen when the source list itself is refused, and raises no failure", async () => {
    stubDay(dayWithAnAnchor(), buildTodayAreas());
    apiServer.use(
      jsonHandler("/api/v1/calendar-sources", {
        status: 503,
        body: {
          type: "syncr:service-unavailable",
          title: "The api is not ready",
          status: 503,
          detail: "The source list could not be read.",
        },
      }),
    );
    const { container } = renderAt("/today");

    expect(await screen.findByText("Lecture · Signals")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".status--error")).toHaveLength(0);
    /* And no feed notice either: a list that did not arrive is not evidence that a feed is stale. */
    expect(noticeSurfaces(container, "amber")).toEqual([]);
  });
});

describe("the write target's token expiring", () => {
  /* THE LOUDEST NON-BLOCKING VOLUME, because it is the most dangerous silent failure in the product: the plan
   * quietly stops reaching the phone and every screen looks healthy. The words are the api's, composed once and
   * raised at two volumes with a shared identity root, so the banner and the Settings panel cannot differ. */
  const expiry = {
    id: "google.write-target-expired.banner",
    volume: "banner",
    pigment: "oxide",
    title: "The plan is not reaching your calendar",
    detail:
      "syncr has not been able to write to your Google calendar for 4 days, so what your phone shows is that " +
      "old. Reading your calendars still works, so the plan itself is current and correct: only the copy on " +
      "Google is stale. Reconnecting your Google account fixes it, and nothing else needs redoing.",
    unavailable: ["Writing the plan to your Google calendar"],
    stillWorks: [
      "Reading your calendars, so the plan is still built around them",
      "Every other part of syncr, including solving and the week you see",
    ],
    since: "2026-08-01T09:14:22Z",
    action: { label: "Reconnect Google", href: "/settings" },
    scope: null,
  };

  it("takes the top bar until it clears, in oxide, with one repair and no way to dismiss it", async () => {
    installWeekReads(buildWeekView());
    apiServer.use(
      googleConnection({
        status: 200,
        body: { configured: true, connected: true, grantedScopes: [], notices: [expiry] },
      }),
    );
    const { container } = renderAt(WEEK_PATH);

    const banner = await waitFor(() => {
      const found = noticeSurfaces(container, "oxide").filter((one) =>
        one.className.includes("notice--banner"),
      );
      expect(found).toHaveLength(1);
      return found[0];
    });

    expect(banner.textContent).toContain("for 4 days");
    expect(banner.textContent).toContain("Reading your calendars still works");
    /* THE BANNER STATES WHAT SURVIVES IN ONE LINE, because a list in the top bar would push the plan down the
     * page. The per-capability rows are the panel volume's form, and the panel for this same condition is on
     * Settings, raised by the api as a second notice with the same identity root. */
    expect(banner.textContent).toContain("still works · Reading your calendars");
    /* ONE repair, because a reader asked to choose between two has been given a decision rather than a fix. */
    expect([...banner.querySelectorAll("a")].map((link) => link.textContent)).toEqual([
      "Reconnect Google",
    ]);
    expect(banner.querySelector("button")).toBeNull();
  });
});

describe("a projection that stopped, which the api pushes rather than waiting to be asked", () => {
  const stopped = {
    id: "calendar.projection-stopped.banner",
    volume: "banner",
    pigment: "oxide",
    title: "The plan is not reaching your calendar",
    detail:
      "Writing the plan to your calendar 'syncr · plan' failed. The provider refused the write. This was " +
      "attempt 3 of 3. Your phone is showing the plan from 4 hours ago.",
    unavailable: ["Writing the plan to your calendar"],
    stillWorks: [
      "The plan itself, which is current and correct in syncr",
      "Reading your calendars, so the plan is still built around them",
    ],
    since: "2026-08-08T05:00:00Z",
    action: { label: "Open calendar settings", href: "/settings" },
    scope: null,
  };

  /* THE PUSH HAS TO REACH THE READER. The api publishes this notice from the failed pass itself rather than
   * leaving it to the next read of Settings, precisely because a stopped projection is the one degradation a
   * reader cannot discover by looking at the plan: the plan is correct and the calendar is quietly stale. A
   * client that dropped the event would show nothing until the reader happened to reload. */
  it("reaches the top bar on the event, without the reader reloading anything", async () => {
    const stream = eventStream();
    installWeekReads(buildWeekView());
    /* The condition is READ rather than taken from the event's payload: the stream states what changed, and the
     * words a reader acts on are composed once, on the server. So the first read carries nothing and the read the
     * event provokes is the one that carries the notice. */
    let reads = 0;
    apiServer.use(
      stream.handler,
      http.get(`${window.location.origin}${CONNECTION_PATH}`, () => {
        reads += 1;
        return HttpResponse.json({
          configured: true,
          connected: true,
          grantedScopes: [],
          notices: reads === 1 ? [] : [stopped],
        });
      }),
    );
    const { container } = renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);
    expect(noticeSurfaces(container, "oxide")).toEqual([]);

    stream.push("notice", stopped);

    await waitFor(() => {
      expect(noticeSurfaces(container, "oxide")).toHaveLength(1);
    });
    expect(reads).toBeGreaterThan(1);
    expect(container.textContent).toContain("attempt 3 of 3");
    expect(container.textContent).toContain("still works · The plan itself");
  });
});

describe("only conflicts notify", () => {
  /* THE SWEEP IS OVER THE STREAM'S OWN UNION, so a fifth event type reaches this case the day it is declared
   * rather than the day someone remembers to extend a list here.
   *
   * WHAT IS ASSERTED PER TYPE is whether the reader is INTERRUPTED while the server holds something they COULD
   * be interrupted with: every case arranges a conflict on the week and a degradation notice on the connection
   * before it pushes. A type that raises nothing therefore refuses to raise something that exists, rather than
   * finding nothing to raise. And the negative arm ends by pushing a conflict and waiting for the notice that
   * follows, which is what proves the window it just measured was long enough to have seen one.
   *
   * A conflict is the one condition in this product that raises a notice nobody asked for. A degradation notice
   * raises one because the api composed it and pushed it, which is a statement about the product rather than a
   * nag about the plan. An operation -- INCLUDING A SUPERSESSION, the expected outcome of editing quickly -- and
   * a completed projection pass raise nothing: a trivial improvement that nagged like a real conflict is how a
   * reader comes to mute the ones that matter. */
  const RAISES_A_NOTICE: Readonly<Record<EventType, boolean>> = {
    conflict: true,
    notice: true,
    operation: false,
    projection: false,
  };

  /* The two arms, partitioned from the union rather than written out, so a fifth type joins one of them. */
  const INTERRUPTS = EVENT_TYPES.filter((type) => RAISES_A_NOTICE[type]);
  const STAYS_SILENT = EVENT_TYPES.filter((type) => !RAISES_A_NOTICE[type]);

  const pushed = {
    id: "calendar.projection-stopped.banner",
    volume: "banner",
    pigment: "oxide",
    title: "The plan is not reaching your calendar",
    detail: "The last write failed.",
    unavailable: ["Writing the plan to your calendar"],
    stillWorks: ["The plan itself, which is current and correct in syncr"],
    since: null,
    action: null,
    scope: null,
  };

  const payloadFor = (type: EventType): unknown => {
    if (type === "conflict") return buildConflict();
    if (type === "notice") return pushed;
    if (type === "operation") return buildOperation({ status: "superseded" });
    return {
      isoWeek: ISO_WEEK,
      pass: {
        inserted: 3,
        patched: 1,
        deleted: 0,
        foreignDeleted: 0,
        unchanged: 88,
        durationMs: 412,
      },
    };
  };

  /**
   * The week screen, with a conflict standing on the server and a degradation notice waiting on the connection.
   *
   * Both conditions are in place before anything is pushed, so a type that raises nothing is refusing to raise
   * something that exists rather than finding nothing to raise.
   */
  async function openWithBothConditionsStanding(): Promise<{
    readonly container: HTMLElement;
    readonly stream: ReturnType<typeof eventStream>;
  }> {
    const stream = eventStream();
    const week = installWeekReads(buildWeekView({ conflicts: [] }));
    let reads = 0;
    apiServer.use(
      stream.handler,
      http.get(`${window.location.origin}${CONNECTION_PATH}`, () => {
        reads += 1;
        return HttpResponse.json({
          configured: true,
          connected: true,
          grantedScopes: [],
          notices: reads === 1 ? [] : [pushed],
        });
      }),
    );
    const { container } = renderAt(WEEK_PATH);
    await screen.findByLabelText(`${LEETCODE} · Career`);
    expect(noticeCount(container)).toBe(0);
    week.serve(buildWeekView({ conflicts: [buildConflict()] }));
    return { container, stream };
  }

  it.each(INTERRUPTS)("a %s event raises the notice its own condition composes", async (type) => {
    const { container, stream } = await openWithBothConditionsStanding();

    stream.push(type, payloadFor(type));

    await waitFor(() => {
      expect(noticeCount(container)).toBeGreaterThan(0);
    });
  });

  it.each(STAYS_SILENT)("a %s event raises nothing, with something to raise", async (type) => {
    const { container, stream } = await openWithBothConditionsStanding();

    stream.push(type, payloadFor(type));
    await settle();

    expect(noticeCount(container)).toBe(0);
    /* THE CONTROL ON THIS ARM. The one thing that does notify is pushed next: the notice appearing now proves the
     * window above was long enough to have shown one, so the silence was the event's own. */
    stream.push("conflict", buildConflict());
    await waitFor(() => {
      expect(noticeCount(container)).toBeGreaterThan(0);
    });
  });

  /* WHAT ACTUALLY GUARDS THIS PARTITION. Asserting the two arms' union equals `EVENT_TYPES` cannot fail: both are
   * built by partitioning it. Two things CAN fail and one of them is a live hole: a fifth event type breaks
   * `Readonly<Record<EventType, boolean>>` at compile time, which `just typecheck-frontend` catches and vitest does
   * not; and at RUNTIME an unlisted type reads `undefined` from the table and would fall silently into the arm that
   * expects nothing. So the runtime hole is closed here rather than restated. */
  it("answers for every type the stream declares, with no type falling through by absence", () => {
    const answered = EVENT_TYPES.filter((type) => typeof RAISES_A_NOTICE[type] === "boolean");

    expect(answered).toEqual([...EVENT_TYPES]);
    expect(INTERRUPTS.length + STAYS_SILENT.length).toBe(EVENT_TYPES.length);
    expect(INTERRUPTS.length).toBeGreaterThan(0);
    expect(STAYS_SILENT.length).toBeGreaterThan(0);
  });
});

/** How many notices, at any volume, the screen is showing. */
function noticeCount(container: ParentNode): number {
  return container.querySelectorAll(".notice").length;
}

/** One turn of the event loop plus a revalidation window, so "nothing happened" is a measured answer. */
async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 60));
}
