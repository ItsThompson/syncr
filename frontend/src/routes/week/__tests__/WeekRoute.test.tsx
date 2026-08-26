/* THE WEEK SCREEN, DRIVEN THROUGH THE REAL ROUTE AND THE REAL CLIENT.
 *
 * What a route test answers that a component test cannot is whether the request the client BUILDS matches the route
 * the api declares, and whether the composed payload survives the trip into a rendering. The interceptor answers at
 * the network layer, so the real client, the real path it assembles from the settled `{iso_week}` spelling, and the
 * real response parsing are all exercised.
 *
 * THE PAYLOADS ARE `./fixtures`, TYPED AGAINST THE GENERATED CLIENT. This file held its own untyped copies first, and
 * they had invented three shapes the api does not produce -- an Area with `targetShare` and `floorMinutesPerWeek`,
 * which the api spells `budgetPercent` and `floorHours`, and a `reviewCadence` of `weekly`, which is not one of the two
 * the enum holds. Every case here passed against all three, because the double takes a body of `unknown`. One typed
 * home per screen is what makes a renamed field a compile error instead of a green test. */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { eventStream, jsonHandler, recordingHandler } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import { GRID_H_PX } from "../../../ui/domain";
import {
  APPLICATION,
  AWAITING_WEEK_FACTS,
  DATES,
  EMPTY_WEEK_FACTS,
  ISO_WEEK,
  LEETCODE,
  SETTINGS,
  SLOT_LABEL,
  WEEK_PATH,
  buildOperation,
  buildPlan,
  buildReadings,
  buildWeekView,
  installWeekReads,
  wholeBandLine,
} from "./fixtures";

/* The axis the fixture's own week yields: the declared bounds run 06:00 to 22:00 and no block lies outside them, so
 * the extent is 960 minutes and every column's canvas is that many minutes of pixels. */
const EXTENT_MINUTES = 16 * 60;

/** The band's own line: the block count and the unconfirmed days, as a reader reads them. The zoom level the band
 * draws lives in the segment beside this line, not in it. */
async function bandLine(): Promise<string> {
  return (await screen.findByText(/blocks ·/)).textContent ?? "";
}

describe("the week the reader asked for", () => {
  it("renders seven columns from the payload's own zone map", async () => {
    installWeekReads(buildWeekView());
    const { container } = renderAt(WEEK_PATH);

    await waitFor(() => {
      expect(container.querySelectorAll(".week-day")).toHaveLength(7);
    });
  });

  it("draws each block once, in the column its own start falls in", async () => {
    installWeekReads(buildWeekView());
    renderAt(WEEK_PATH);

    expect(await screen.findByLabelText(`${LEETCODE} · Career`)).toBeInTheDocument();
    expect(screen.getByLabelText(`${APPLICATION} · Career`)).toBeInTheDocument();
  });

  it("draws the forbidden window's STORED label in the gutter", async () => {
    installWeekReads(buildWeekView());
    renderAt(WEEK_PATH);

    expect(await screen.findByText("recovery · Kontron Interview")).toBeInTheDocument();
  });

  /* BOTH GUTTER SENTENCES ARE THE PAYLOAD'S. The window's is the stored one and the slot's is rendered by the
   * server from the one wording its reason has, so neither is composed on this screen. What is also asserted is
   * that the band draws AT ALL: a gap left as nothing is pixel-identical to an ordinary gap, which is the defect
   * the band exists to prevent. */
  it("draws the empty slot's band and the wording the payload carried for it", async () => {
    installWeekReads(buildWeekView());
    const { container } = renderAt(WEEK_PATH);

    await waitFor(() => {
      expect(container.querySelectorAll(".week-band")).toHaveLength(2);
    });
    expect(container.querySelectorAll(".week-band__label")).toHaveLength(2);
    expect(screen.getByText(SLOT_LABEL)).toBeInTheDocument();
  });

  it("reads the strip's three figures and the currency from the payload", async () => {
    installWeekReads(buildWeekView());
    renderAt(WEEK_PATH);

    expect(await screen.findByText("80.8h")).toBeInTheDocument();
    expect(screen.getByText("52.1h")).toBeInTheDocument();
    expect(screen.getByText("18.4h")).toBeInTheDocument();
    expect(screen.getByText("91 blocks")).toBeInTheDocument();
  });

  it("qualifies the block count while a solve is in flight, rather than spinning", async () => {
    installWeekReads(buildWeekView({ readings: buildReadings({ planCurrency: "solving" }) }));
    renderAt(WEEK_PATH);

    expect(await screen.findByText("91 · solving")).toBeInTheDocument();
  });

  it("labels each column with its weekday and date", async () => {
    installWeekReads(buildWeekView());
    renderAt(WEEK_PATH);

    expect(await screen.findByText("MON 09")).toBeInTheDocument();
    expect(screen.getByText("SUN 15")).toBeInTheDocument();
  });

  /* THE SETTING TRAVELS UNCLAMPED AND THE GRID BRINGS IT INSIDE ITS OWN MEASURED RANGE. A 24-hour setting would draw
   * a thirty-minute block at 13px, below the label floor, which is the one thing the clamp exists to prevent. The
   * canvas height is where that is observable: pixels per minute is the grid height over the VISIBLE minutes, so a
   * clamped setting produces a taller canvas for the same extent.
   *
   * The clamp is the GRID's, against the height it measures, which is why this asserts the rendering rather than a
   * prop: in a headless DOM nothing is laid out, so the measurement falls back to the reference display's grid and
   * the cap is that display's 16. In a browser the cap is the real display's, which is the whole point of moving the
   * clamp down here: clamping above the grid capped a 27 inch reader at the 13 inch reference. */
  it("renders a 24-hour setting at the measured display's own cap of 16 hours", async () => {
    installWeekReads(buildWeekView());
    apiServer.use(
      jsonHandler("/api/v1/settings", { status: 200, body: { ...SETTINGS, visibleHours: 24 } }),
    );
    const { container } = renderAt(WEEK_PATH);

    await screen.findByText("MON 09");
    const canvas = container.querySelector(".week-day__canvas");
    const atTheCap = (EXTENT_MINUTES * (GRID_H_PX / (16 * 60))).toFixed(3);
    const unclamped = (EXTENT_MINUTES * (GRID_H_PX / (24 * 60))).toFixed(3);

    expect(canvas).toHaveStyle({ height: `${atTheCap}px` });
    expect(canvas).not.toHaveStyle({ height: `${unclamped}px` });
  });
});

/* THE COUNT OF UNCONFIRMED DAYS IS THE WEEK READ'S OWN FIGURE. The payload says nothing about any day's
 * confirmation, so a screen deriving this from what it drew would be a second rule with less to go on than the
 * api's, and it would disagree with the Today band about the same week. */
describe("the week's count of unconfirmed days", () => {
  /** How many of the week's dates the fixture's plan puts a block on, which is what counting the drawn rows reaches. */
  const DAYS_HOLDING_A_BLOCK = new Set(
    buildPlan().blocks.map((block) => block.interval.start.slice(0, 10)),
  ).size;

  const SERVED = 5;

  it("renders the served figure rather than the one its own drawn days imply", async () => {
    expect(DAYS_HOLDING_A_BLOCK, "the drawn days must disagree with the served figure").not.toBe(
      SERVED,
    );
    expect(DATES.length, "and so must the seven columns").not.toBe(SERVED);
    const readings = buildReadings({ unconfirmedDays: SERVED });
    installWeekReads(buildWeekView({ readings }));
    renderAt(WEEK_PATH);

    expect(await bandLine()).toBe(wholeBandLine(readings.blockCount, `${SERVED} days unconfirmed`));
  });

  /* NOUGHT IS PRINTED, NOT DROPPED, which is what the band's other cells do with theirs: the block count reads
   * `0 blocks` on a week holding none. The thing that disappears at nought is Today's backfill control, which is a
   * control with nothing to do rather than a reading with nothing to say. */
  it("prints a nought the way the band's other cells print theirs", async () => {
    const readings = buildReadings({ blockCount: 0, unconfirmedDays: 0 });
    installWeekReads(buildWeekView({ readings }));
    renderAt(WEEK_PATH);

    expect(await bandLine()).toBe(wholeBandLine(readings.blockCount, "0 days unconfirmed"));
  });

  /* THREE READINGS RATHER THAN ONE. A literal, a hard-coded plural and a figure read off a neighbouring field each
   * satisfy one of these and not all three, and one is the direction a week that goes fully unanswered takes. */
  it.each([
    [1, "1 day unconfirmed"],
    [DATES.length, `${DATES.length} days unconfirmed`],
  ])("reads %i as `%s`", async (unconfirmedDays, reading) => {
    const readings = buildReadings({ unconfirmedDays });
    installWeekReads(buildWeekView({ readings }));
    renderAt(WEEK_PATH);

    expect(await bandLine()).toBe(wholeBandLine(readings.blockCount, reading));
  });
});

describe("a week with no plan", () => {
  it("says why, in the server's own sentence, and offers the horizon's two repairs", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: EMPTY_WEEK_FACTS,
      }),
    );
    renderAt(WEEK_PATH);

    expect(
      await screen.findByText(
        "This week is beyond your 14-day planning horizon, which reaches 1 February.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Extend the horizon" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
  });

  it("draws no grid at all, so an empty state and a grid can never be on screen together", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: EMPTY_WEEK_FACTS,
      }),
    );
    const { container } = renderAt(WEEK_PATH);

    await screen.findByRole("button", { name: "Solve this week now" });
    expect(container.querySelector(".week-grid")).toBeNull();
  });

  it("offers one repair for a missing input, and points it at the setup route", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "setup_incomplete",
        emptyWeek: {
          ...EMPTY_WEEK_FACTS,
          coversThisWeek: true,
          missingInputs: ["areas"],
          statement: "Declare at least one Area and a day shape for each weekday.",
        },
      }),
    );
    renderAt(WEEK_PATH);

    expect(await screen.findByRole("link", { name: "Finish setting up" })).toHaveAttribute(
      "href",
      "/setup",
    );
    expect(screen.queryByRole("link", { name: "Extend the horizon" })).toBeNull();
  });

  it("says a week inside the horizon is being planned, and offers only the solve", async () => {
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "awaiting_maintainer",
        emptyWeek: AWAITING_WEEK_FACTS,
      }),
    );
    const { container } = renderAt(WEEK_PATH);

    expect(await screen.findByText(AWAITING_WEEK_FACTS.statement)).toBeInTheDocument();
    /* THE HEADING IS READ BESIDE THE SENTENCE, because a heading that contradicts its own body is green against an
     * assertion on either half alone: the sentence says the week is inside the horizon, and a heading borrowed from
     * the state beyond it offers to extend a horizon that already reaches the week. */
    expect(container.querySelector(".status__title")?.textContent).toBe(
      "syncr is planning this week",
    );
    expect(screen.getByRole("button", { name: "Solve this week now" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Extend the horizon" })).toBeNull();
  });

  /* THE WAIT ENDS WITHOUT THE READER DOING ANYTHING, which is what makes the state a wait rather than a dead end.
   * The screen holds the operation the payload named, the push channel says it succeeded, and the week's own key is
   * invalidated: one refetch, one redraw, no press. The plan arriving is asserted through a block the grid draws,
   * because the empty state disappearing is also what an error state would produce. */
  it("renders the plan once the revision is appended, with nothing asked of the reader", async () => {
    const stream = eventStream();
    const week = installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "awaiting_maintainer",
        emptyWeek: AWAITING_WEEK_FACTS,
        operation: buildOperation({ status: "pending" }),
      }),
    );
    apiServer.use(stream.handler);
    renderAt(WEEK_PATH);
    await screen.findByText(AWAITING_WEEK_FACTS.statement);

    week.serve(buildWeekView());
    stream.push("operation", buildOperation({ status: "succeeded" }));

    expect(await screen.findByLabelText(`${LEETCODE} · Career`)).toBeInTheDocument();
    expect(screen.queryByText(AWAITING_WEEK_FACTS.statement)).toBeNull();
  });

  it("asks for a solve at the week's own path, bypassing the debounce", async () => {
    const solve = recordingHandler("post", `/api/v1/weeks/${ISO_WEEK}/solve`, {
      status: 202,
      body: null,
    });
    installWeekReads(
      buildWeekView({
        live: null,
        readings: null,
        emptyReason: "outside_horizon",
        emptyWeek: EMPTY_WEEK_FACTS,
      }),
    );
    apiServer.use(solve.handler);
    renderAt(WEEK_PATH);

    (await screen.findByRole("button", { name: "Solve this week now" })).click();

    await waitFor(() => {
      expect(solve.bodies).toHaveLength(1);
    });
  });
});

describe("a week the api refuses", () => {
  it("says the plan was not read and leaves the reader's plan unchanged", async () => {
    /* The three reads, with the week's own answering a refusal rather than a view: `installWeekReads` serves a view, so
     * the refusal is installed over it. Later handlers win in msw, which is what makes this an override of one read
     * rather than a second copy of all three. */
    installWeekReads(buildWeekView());
    apiServer.use(
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
    renderAt(WEEK_PATH);

    expect(await screen.findByText("iso_week is not an ISO week identifier.")).toBeInTheDocument();
  });

  /* THE FIGURES AND THE PLAN ARRIVE TOGETHER OR NOT AT ALL: `readings` is null exactly when `live` is, which is the
   * endpoint's own biconditional. A payload holding one without the other is a response the server does not produce,
   * and it is read as NOT YET READABLE rather than rendered with holes: a strip drawing three empty cells over a real
   * grid would state figures nobody computed. Checking `live` alone leaves that reachable, so the pair is checked. */
  it("treats a plan with no figures as not yet readable rather than drawing it with holes", async () => {
    installWeekReads(buildWeekView({ readings: null }));
    renderAt(WEEK_PATH);

    expect(await screen.findByText("Reading this week")).toBeInTheDocument();
  });
});
