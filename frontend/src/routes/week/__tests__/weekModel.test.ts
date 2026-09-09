/* THE SEVEN COLUMNS, AND THE THREE THINGS THAT MUST BE TRUE OF THEM ON A DST WEEK.
 *
 * A local day is 23, 24 or 25 hours long and the figure comes from INSTANTS, so the axis stays proportional across a
 * transition with no special case. NO BLOCK IS CLIPPED: the minutes a block occupies across all seven columns equal
 * its own duration, which is the assertion the axis rule reduces to once a span crossing midnight is cut per column.
 * And the declared day bounds are a DEFAULT: a block outside them widens the extent instead of being cropped by it.
 *
 * Both weeks come from the domain's own `dst_weeks` fixture, so a DST claim here is made against the dates every
 * other layer's DST claims are made against. */

import { describe, expect, it } from "vitest";

import { zonedInstant } from "../../../lib/zonedInstant";
import { DST_WEEKS, FALL_BACK, SPRING_FORWARD, zoneByDateOf } from "../../../testing/dstWeeks";
import type { DstWeek } from "../../../testing/dstWeeks";
import { weekModel, type DayBounds } from "../weekModel";
import type { WeekBand } from "../bands";
import type { WeekBlock } from "../blocks";

const BOUNDS: DayBounds = { startMin: 6 * 60, endMin: 22 * 60 };
const MILLISECONDS_IN_MINUTE = 60_000;

/* A WALL TIME IN THE WEEK'S OWN ZONE, because a block's stored instant came from one. Writing the fixtures in UTC
 * put a 23:00 local block an hour into the following day for the whole of British Summer Time, which is the defect
 * this helper exists to make unwriteable. The column starts these are measured against are pinned to the domain's
 * own literal instants by the assertions above, so nothing here rests on the resolver being right. */
function wall(week: DstWeek, date: string, clock: string): number {
  const [hours, minutes] = clock.split(":").map(Number);
  const resolved = zonedInstant({ date, minutes: hours * 60 + minutes, zone: week.zone });
  if (resolved === null) throw new Error(`${date} ${clock} does not resolve in ${week.zone}`);
  return Date.parse(resolved.instant);
}

function block(id: string, startMs: number, endMs: number): WeekBlock {
  return {
    id,
    title: id,
    origin: "frame",
    pigment: null,
    areaName: null,
    isPinned: false,
    staleSourceId: null,
    startMs,
    endMs,
  };
}

function band(id: string, startMs: number, endMs: number): WeekBand {
  return {
    id,
    startMs,
    endMs,
    label: "recovery · Kontron Interview",
    reason: "recovery",
  };
}

/** The day before an ISO date, so a span can be given a start outside the week under test. */
function previousDate(isoDate: string): string {
  const at = new Date(`${isoDate}T00:00:00Z`);
  at.setUTCDate(at.getUTCDate() - 1);
  return at.toISOString().slice(0, 10);
}

function modelOf(
  week: DstWeek,
  blocks: readonly WeekBlock[] = [],
  bands: readonly WeekBand[] = [],
) {
  return weekModel({
    zoneByDate: zoneByDateOf(week),
    spanEnd: week.spanEnd,
    bounds: BOUNDS,
    blocks,
    bands,
  });
}

describe.each(DST_WEEKS)("$label", (week: DstWeek) => {
  it("draws seven columns, one per date in the week's own zone map", () => {
    const { days } = modelOf(week);

    expect(days.map((day) => day.date)).toEqual([...week.dates]);
  });

  it("starts each column at the instant its own local date does", () => {
    const { days } = modelOf(week);
    const transition = days.at(-1);

    expect(transition?.startMs).toBe(Date.parse(week.transitionDayStart));
  });

  it("reads the transition day's length from instants: 23 or 25 hours, never an assumed 1440", () => {
    const { days } = modelOf(week);

    expect(days.at(-1)?.minutes).toBe(week.transitionDayMinutes);
    expect(days.at(-1)?.minutes).not.toBe(24 * 60);
  });

  it("reads every other day as 1440 minutes, so only the transition day differs", () => {
    const { days } = modelOf(week);

    expect(days.slice(0, 6).map((day) => day.minutes)).toEqual(Array<number>(6).fill(1440));
  });

  it("holds the transition day's last minute once a block reaches it, so the 25th hour is drawable", () => {
    const late = block(
      "late",
      wall(week, week.transitionDate, "23:00"),
      Date.parse(week.transitionDayEnd),
    );
    const { extent } = modelOf(week, [late]);

    expect(extent.endMin).toBeGreaterThanOrEqual(week.transitionDayMinutes);
  });

  it("holds the declared bounds and no more on a week holding nothing, because bounds are a DEFAULT", () => {
    const { extent } = modelOf(week);

    expect(extent.endMin).toBeLessThan(24 * 60);
  });
});

/* THE DECLARED BOUNDS ARE WALL TIMES AND THE AXIS IS A DURATION, so a transition inside the day moves the bounds
 * within it. 06:00 sits 300 minutes into the spring-forward day, because the hour between 01:00 and 02:00 does not
 * exist; 22:00 sits 1380 minutes into the fall-back day, because the hour between 01:00 and 02:00 happens twice. One
 * axis serves seven columns, so it takes the widest reading of the bounds across them rather than one column's.
 * These are the two figures a shared axis that assumed a fixed offset would get wrong. */
describe("the bounds read across a transition", () => {
  it("starts 300 minutes in on a spring-forward week, an hour earlier than the other six days", () => {
    expect(
      weekModel({
        zoneByDate: zoneByDateOf(SPRING_FORWARD),
        spanEnd: SPRING_FORWARD.spanEnd,
        bounds: BOUNDS,
        blocks: [],
        bands: [],
      }).extent,
    ).toEqual({ startMin: 300, endMin: 1320 });
  });

  it("ends 1380 minutes in on a fall-back week, an hour later than the other six days", () => {
    expect(
      weekModel({
        zoneByDate: zoneByDateOf(FALL_BACK),
        spanEnd: FALL_BACK.spanEnd,
        bounds: BOUNDS,
        blocks: [],
        bands: [],
      }).extent,
    ).toEqual({ startMin: 360, endMin: 1380 });
  });
});

/* THE ONE SPAN THAT PROVES THE BOUNDARY RULE. `Sleep 23:00 + 8h` on the last night starts inside the week and ends
 * inside the next one, so its tail has no column of its own. It is drawn past the last column's day end rather than
 * shortened, and the extent expands to hold it. */
describe("the Sunday-night frame occurrence", () => {
  const week = SPRING_FORWARD;
  const sleep = block(
    "sleep",
    Date.parse(week.sundayNightFrameStart),
    Date.parse(week.sundayNightFrameEnd),
  );

  it("is drawn in the last column and in no other", () => {
    const { days } = modelOf(week, [sleep]);
    const holding = days.filter((day) => day.blocks.length > 0);

    expect(holding.map((day) => day.date)).toEqual([week.dates.at(-1)]);
  });

  it("keeps its whole eight hours rather than being cut at the column's end", () => {
    const { days } = modelOf(week, [sleep]);
    const drawn = days.at(-1)?.blocks[0].span;

    expect((drawn?.endMin ?? 0) - (drawn?.startMin ?? 0)).toBe(8 * 60);
  });

  it("widens the extent past the end of the local day, so nothing about it is hidden", () => {
    const { days, extent } = modelOf(week, [sleep]);
    const drawn = days.at(-1)?.blocks[0].span;

    expect(extent.endMin).toBeGreaterThanOrEqual(drawn?.endMin ?? 0);
    expect(extent.endMin).toBeGreaterThan(week.transitionDayMinutes);
  });
});

describe("a span crossing midnight inside the week", () => {
  const week = FALL_BACK;
  const sleep = block(
    "sleep",
    wall(week, week.dates[1], "23:00"),
    wall(week, week.dates[2], "07:00"),
  );

  it("is drawn in both columns it touches", () => {
    const { days } = modelOf(week, [sleep]);
    const holding = days.filter((day) => day.blocks.length > 0).map((day) => day.date);

    expect(holding).toEqual([week.dates[1], week.dates[2]]);
  });

  it("is CLIPPED BY NOTHING: the two pieces sum to its own duration", () => {
    const { days } = modelOf(week, [sleep]);
    const drawnMinutes = days
      .flatMap((day) => day.blocks)
      .reduce((total, piece) => total + (piece.span.endMin - piece.span.startMin), 0);

    expect(drawnMinutes).toBe((sleep.endMs - sleep.startMs) / MILLISECONDS_IN_MINUTE);
  });

  it("meets the column boundary from both sides, so there is no gap at midnight", () => {
    const { days } = modelOf(week, [sleep]);
    const [first, second] = days.filter((day) => day.blocks.length > 0);

    expect(first.blocks[0].span.endMin).toBe(first.minutes);
    expect(second.blocks[0].span.startMin).toBe(0);
  });
});

describe("no block is clipped, on either week and at every edge", () => {
  /* THE INVARIANT HAS TWO BOUNDS AND ONLY ONE OF THEM IS UNCONDITIONAL. Nothing is clipped for a span that starts
   * inside the week: the pieces sum to its own duration, asserted below over six shapes per week. A span that starts
   * BEFORE the week IS clipped at the first column, and that is correct rather than a defect: the minutes before
   * Monday's own midnight are last week's, and drawing them above Monday's midnight line would put another week's
   * time on this axis. Asserted so the invariant reads as bounded rather than as absolute.
   *
   * Whether the api sends a preceding week's frame occurrence at all is a different question and a server one: if it
   * does not, Monday's small hours read as free while they are occupied. The arithmetic here is right either way. */
  it.each(DST_WEEKS)("$label clips a span that began before the week", (week: DstWeek) => {
    const before = block(
      "leading-overhang",
      wall(week, previousDate(week.dates[0]), "22:00"),
      wall(week, week.dates[0], "06:00"),
    );
    const { days } = modelOf(week, [before]);
    const pieces = days.flatMap((day) => day.blocks);
    const drawn = pieces.reduce(
      (total, piece) => total + (piece.span.endMin - piece.span.startMin),
      0,
    );

    expect(pieces).toHaveLength(1);
    expect(pieces[0].span.startMin).toBe(0);
    expect(drawn).toBe(6 * 60);
    expect(drawn).toBeLessThan((before.endMs - before.startMs) / MILLISECONDS_IN_MINUTE);
  });

  it.each(DST_WEEKS)("$label", (week: DstWeek) => {
    const blocks = [
      block("overnight", wall(week, week.dates[0], "22:30"), wall(week, week.dates[1], "06:30")),
      block(
        "across-the-transition",
        wall(week, week.transitionDate, "00:30"),
        wall(week, week.transitionDate, "03:30"),
      ),
      block(
        "before-the-bounds",
        wall(week, week.dates[3], "04:00"),
        wall(week, week.dates[3], "05:00"),
      ),
      block(
        "after-the-bounds",
        wall(week, week.dates[3], "22:30"),
        wall(week, week.dates[3], "23:45"),
      ),
      block("zero-length", wall(week, week.dates[4], "09:00"), wall(week, week.dates[4], "09:00")),
      block("tail", Date.parse(week.sundayNightFrameStart), Date.parse(week.sundayNightFrameEnd)),
    ];
    const { days, extent } = modelOf(week, blocks);

    for (const original of blocks) {
      const drawn = days
        .flatMap((day) => day.blocks)
        .filter((piece) => piece.id === original.id)
        .reduce((total, piece) => total + (piece.span.endMin - piece.span.startMin), 0);

      expect(drawn, `${original.id} lost minutes`).toBe(
        (original.endMs - original.startMs) / MILLISECONDS_IN_MINUTE,
      );
    }

    for (const piece of days.flatMap((day) => day.blocks)) {
      expect(piece.span.startMin).toBeGreaterThanOrEqual(extent.startMin);
      expect(piece.span.endMin).toBeLessThanOrEqual(extent.endMin);
    }
  });
});

describe("a zero-length block", () => {
  const week = SPRING_FORWARD;

  it("is placed in the column holding its instant, and in exactly one", () => {
    const instant = wall(week, week.dates[2], "09:00");
    const { days } = modelOf(week, [block("empty", instant, instant)]);
    const holding = days.filter((day) => day.blocks.length > 0);

    expect(holding.map((day) => day.date)).toEqual([week.dates[2]]);
  });

  it("is placed at midnight rather than in the day before, where the boundary is its own start", () => {
    const midnight = wall(week, week.dates[2], "00:00");
    const { days } = modelOf(week, [block("empty", midnight, midnight)]);
    const holding = days.filter((day) => day.blocks.length > 0);

    expect(holding.map((day) => day.date)).toEqual([week.dates[2]]);
    expect(holding[0].blocks[0].span).toEqual({ startMin: 0, endMin: 0 });
  });
});

describe("the declared day bounds", () => {
  const week = FALL_BACK;

  it("set the default extent on a week holding nothing at all", () => {
    const { extent } = modelOf(week);

    expect(extent.startMin).toBe(BOUNDS.startMin);
  });

  it("are read in each column's own zone, so the transition day's 22:00 is 1380 minutes in", () => {
    const { extent } = modelOf(week);

    expect(extent.endMin).toBe(23 * 60);
  });

  it("never crop: a block before the day starts widens the axis instead", () => {
    const early = block(
      "early",
      wall(week, week.dates[0], "01:00"),
      wall(week, week.dates[0], "02:00"),
    );
    const { extent } = modelOf(week, [early]);

    expect(extent.startMin).toBe(60);
  });
});

describe("a band", () => {
  const week = SPRING_FORWARD;

  it("is cut per column like a block, so a span across three days draws in three", () => {
    const offPlan = band(
      "off-plan",
      wall(week, week.dates[1], "09:00"),
      wall(week, week.dates[3], "09:00"),
    );
    const { days } = modelOf(week, [], [offPlan]);
    const holding = days.filter((day) => day.bands.length > 0).map((day) => day.date);

    expect(holding).toEqual([week.dates[1], week.dates[2], week.dates[3]]);
  });

  it("widens the extent exactly as a block does, because a gap is as unhideable as a block", () => {
    const overnight = band(
      "overnight",
      wall(week, week.dates[1], "02:00"),
      wall(week, week.dates[1], "04:00"),
    );
    const { extent } = modelOf(week, [], [overnight]);

    expect(extent.startMin).toBe(120);
  });

  it("carries its label and its reason through unchanged", () => {
    const window = band(
      "recovery",
      wall(week, week.dates[1], "16:45"),
      wall(week, week.dates[1], "18:00"),
    );
    const { days } = modelOf(week, [], [window]);
    const drawn = days.flatMap((day) => day.bands)[0];

    expect(drawn.label).toBe("recovery · Kontron Interview");
    expect(drawn.reason).toBe("recovery");
  });

  it("marks only the day holding an imported block whose source is possibly stale", () => {
    const imported = {
      ...block("imported", wall(week, week.dates[1], "09:00"), wall(week, week.dates[1], "10:00")),
      staleSourceId: "8c2e0d4f-6a12-4f3a-8b21-7d2b1a904c70",
    };
    const { days } = modelOf(week, [imported]);

    expect(days.map((day) => day.marks?.length ?? 0)).toEqual([0, 1, 0, 0, 0, 0, 0]);
  });
});
