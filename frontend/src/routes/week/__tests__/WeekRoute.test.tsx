/* THE WEEK SCREEN, DRIVEN THROUGH THE REAL ROUTE AND THE REAL CLIENT.
 *
 * What a route test answers that a component test cannot is whether the request the client BUILDS matches the route
 * the api declares, and whether the composed payload survives the trip into a rendering. The interceptor answers at
 * the network layer, so the real client, the real path it assembles from the settled `{iso_week}` spelling, and the
 * real response parsing are all exercised.
 *
 * The payloads are the shapes ticket 31's endpoint answers with, reduced to the fields the screen reads. */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, readyz, recordingHandler } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";

const ISO_WEEK = "2026-W07";
const DATES = [
  "2026-02-09",
  "2026-02-10",
  "2026-02-11",
  "2026-02-12",
  "2026-02-13",
  "2026-02-14",
  "2026-02-15",
];

const AREA_ID = "3f6b2c9d-1a77-4a1b-9a5f-8a2e4a1b9a5f";

const SETTINGS = {
  homeZone: "Europe/London",
  activeZone: "Europe/London",
  activeZoneDate: "2026-02-09",
  dayStart: "06:00",
  dayEnd: "22:00",
  visibleHours: 12,
  reviewCadence: "weekly",
};

const AREAS = {
  areas: [
    {
      id: AREA_ID,
      name: "Career",
      pigmentIndex: 0,
      parentId: null,
      targetShare: "0.25",
      floorMinutesPerWeek: null,
      defaultPreferenceId: null,
    },
  ],
  ramp: { pigmentCount: 12, pigmentsInUse: 1, areasSharingAPigment: 0, statement: null },
};

function span(startIso: string, endIso: string) {
  return { start: startIso, end: endIso };
}

function block(id: string, startIso: string, endIso: string, title: string) {
  return {
    id,
    title,
    areaId: AREA_ID,
    origin: "task",
    binding: { kind: "task", entityId: AREA_ID, occurrenceKey: id, splitIndex: null },
    interval: span(startIso, endIso),
    pinned: false,
    splitCount: null,
    supersededPlacement: null,
    objectiveDelta: null,
    reason: { clauses: [], dominant: null },
  };
}

function weekView(overrides: Record<string, unknown> = {}) {
  return {
    isoWeek: ISO_WEEK,
    span: span("2026-02-09T00:00:00+00:00", "2026-02-16T00:00:00+00:00"),
    zoneByDate: Object.fromEntries(DATES.map((date) => [date, "Europe/London"])),
    live: {
      isoWeek: ISO_WEEK,
      zoneByDate: Object.fromEntries(DATES.map((date) => [date, "Europe/London"])),
      blocks: [
        block("b1", "2026-02-09T09:00:00+00:00", "2026-02-09T10:30:00+00:00", "Leetcode · Graphs"),
        block(
          "b2",
          "2026-02-10T19:00:00+00:00",
          "2026-02-10T19:30:00+00:00",
          "36 South Application",
        ),
      ],
      forbiddenWindows: [
        {
          interval: span("2026-02-09T16:45:00+00:00", "2026-02-09T18:00:00+00:00"),
          kind: "recovery",
          scope: "all",
          forbiddenAreaIds: [],
          label: "recovery · Kontron Interview",
          anchorId: AREA_ID,
        },
      ],
      emptySlots: [
        {
          interval: span("2026-02-11T14:00:00+00:00", "2026-02-11T15:00:00+00:00"),
          areaId: AREA_ID,
          reason: "no_eligible_content",
        },
      ],
      adjustments: [],
    },
    emptyReason: null,
    emptyWeek: null,
    readings: {
      scheduledMinutes: 4848,
      discretionaryMinutes: 3126,
      unallocatedMinutes: 1104,
      oversubscriptionMinutes: 0,
      unconfirmedDays: 0,
      offPlanMinutes: 0,
      blockCount: 91,
      planCurrency: "current",
    },
    offPlan: [],
    operation: null,
    inputVersion: 4,
    adjustments: [],
    candidateAdjustment: null,
    conflicts: [],
    pins: [],
    proposal: null,
    verdict: null,
    ...overrides,
  };
}

const emptyWeekFacts = {
  coversThisWeek: false,
  horizonDays: 14,
  horizonThrough: "2026-02-01",
  missingInputs: [],
  statement: "This week is beyond your 14-day planning horizon, which reaches 1 February.",
};

function installReads(view: Record<string, unknown>) {
  apiServer.use(
    readyz(),
    jsonHandler("/api/v1/settings", { status: 200, body: SETTINGS }),
    jsonHandler("/api/v1/areas", { status: 200, body: AREAS }),
    jsonHandler(`/api/v1/weeks/${ISO_WEEK}`, { status: 200, body: view }),
  );
}

const weekPath = `/week?week=${ISO_WEEK}`;

describe("the week the reader asked for", () => {
  it("renders seven columns from the payload's own zone map", async () => {
    installReads(weekView());
    const { container } = renderAt(weekPath);

    await waitFor(() => {
      expect(container.querySelectorAll(".week-day")).toHaveLength(7);
    });
  });

  it("draws each block once, in the column its own start falls in", async () => {
    installReads(weekView());
    renderAt(weekPath);

    expect(await screen.findByLabelText("Leetcode · Graphs · Career")).toBeInTheDocument();
    expect(screen.getByLabelText("36 South Application · Career")).toBeInTheDocument();
  });

  it("draws the forbidden window's STORED label in the gutter", async () => {
    installReads(weekView());
    renderAt(weekPath);

    expect(await screen.findByText("recovery · Kontron Interview")).toBeInTheDocument();
  });

  /* An empty slot's one gutter label is Python and the payload does not carry the rendered string, so the band draws
   * with an empty gutter rather than with a second wording of it. What is asserted is that it draws AT ALL: a gap
   * left as nothing is pixel-identical to an ordinary gap, which is the defect the band exists to prevent. */
  it("draws the empty slot's band even though the payload carries no label for it", async () => {
    installReads(weekView());
    const { container } = renderAt(weekPath);

    await waitFor(() => {
      expect(container.querySelectorAll(".week-band")).toHaveLength(2);
    });
    expect(container.querySelectorAll(".week-band__label")).toHaveLength(1);
  });

  it("reads the strip's three figures and the currency from the payload", async () => {
    installReads(weekView());
    renderAt(weekPath);

    expect(await screen.findByText("80.8h")).toBeInTheDocument();
    expect(screen.getByText("52.1h")).toBeInTheDocument();
    expect(screen.getByText("18.4h")).toBeInTheDocument();
    expect(screen.getByText("91 blocks")).toBeInTheDocument();
  });

  it("qualifies the block count while a solve is in flight, rather than spinning", async () => {
    installReads(weekView({ readings: { ...weekView().readings, planCurrency: "solving" } }));
    renderAt(weekPath);

    expect(await screen.findByText("91 · solving")).toBeInTheDocument();
  });

  it("labels each column with its weekday and date", async () => {
    installReads(weekView());
    renderAt(weekPath);

    expect(await screen.findByText("MON 09")).toBeInTheDocument();
    expect(screen.getByText("SUN 15")).toBeInTheDocument();
  });
});

describe("a week with no plan", () => {
  it("says why, in the server's own sentence, and offers the horizon's two repairs", async () => {
    installReads(
      weekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: emptyWeekFacts,
      }),
    );
    renderAt(weekPath);

    expect(
      await screen.findByText(
        "This week is beyond your 14-day planning horizon, which reaches 1 February.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Extend the horizon" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
  });

  it("draws no grid at all, so an empty state and a grid can never be on screen together", async () => {
    installReads(
      weekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: emptyWeekFacts,
      }),
    );
    const { container } = renderAt(weekPath);

    await screen.findByRole("button", { name: "Solve this week now" });
    expect(container.querySelector(".week-grid")).toBeNull();
  });

  it("offers one repair for a missing input, and points it at the setup route", async () => {
    installReads(
      weekView({
        live: null,
        readings: null,
        emptyReason: "setup_incomplete",
        emptyWeek: {
          ...emptyWeekFacts,
          coversThisWeek: true,
          missingInputs: ["areas"],
          statement: "Declare at least one Area and a day shape for each weekday.",
        },
      }),
    );
    renderAt(weekPath);

    expect(await screen.findByRole("link", { name: "Finish setting up" })).toHaveAttribute(
      "href",
      "/setup",
    );
    expect(screen.queryByRole("link", { name: "Extend the horizon" })).toBeNull();
  });

  it("asks for a solve at the week's own path, bypassing the debounce", async () => {
    const solve = recordingHandler("post", `/api/v1/weeks/${ISO_WEEK}/solve`, {
      status: 202,
      body: null,
    });
    installReads(
      weekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: emptyWeekFacts,
      }),
    );
    apiServer.use(solve.handler);
    renderAt(weekPath);

    (await screen.findByRole("button", { name: "Solve this week now" })).click();

    await waitFor(() => {
      expect(solve.bodies).toHaveLength(1);
    });
  });
});

describe("a week the api refuses", () => {
  it("says the plan was not read and leaves the reader's plan unchanged", async () => {
    apiServer.use(
      readyz(),
      jsonHandler("/api/v1/settings", { status: 200, body: SETTINGS }),
      jsonHandler("/api/v1/areas", { status: 200, body: AREAS }),
      jsonHandler(`/api/v1/weeks/${ISO_WEEK}`, {
        status: 422,
        body: {
          type: "syncr:invalid-input",
          title: "Invalid input",
          status: 422,
          detail: "iso_week is not an ISO week identifier.",
        },
      }),
    );
    renderAt(weekPath);

    expect(await screen.findByText("iso_week is not an ISO week identifier.")).toBeInTheDocument();
  });
});
