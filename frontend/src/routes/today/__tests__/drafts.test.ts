/* What the two controls open with, and what each one sends.
 *
 * THE PREFILL IS THE CLAIM. A stepper opening at the planned duration and an interval opening at the planned
 * interval are what make the common correction two adjustments, so both are asserted against a row rather
 * than against a literal.
 *
 * THE SENDABLE RULE IS THE OTHER CLAIM. Every figure this screen will not send is a figure the api would
 * refuse, and a bound stated at the control beats a 422 the reader has to read. */

import { describe, expect, it } from "vitest";

import { clockIn } from "../instants";
import {
  MAX_ACTUAL_MINUTES,
  MIN_ACTUAL_MINUTES,
  bodyFor,
  isSendable,
  movedFormFor,
  partialFormFor,
  stateBody,
} from "../drafts";
import { BLOCK_LEETCODE, DATE, ISO_WEEK, ZONE, buildRow } from "./fixtures";

const context = { date: DATE, zone: ZONE, isoWeek: ISO_WEEK };

describe("partialFormFor", () => {
  it("opens at the block's planned duration, on the block it was given", () => {
    expect(partialFormFor(buildRow())).toEqual({
      kind: "partial",
      blockId: BLOCK_LEETCODE,
      minutes: 210,
    });
  });
});

describe("movedFormFor", () => {
  it("opens at the planned interval, read in the day's own zone", () => {
    expect(movedFormFor(buildRow(), ZONE)).toEqual({
      kind: "moved",
      blockId: BLOCK_LEETCODE,
      range: { start: "13:30", end: "17:00" },
    });
  });

  it("opens at the same instants read elsewhere, so a travelling reader sees one zone", () => {
    expect(movedFormFor(buildRow(), "Pacific/Kiritimati").range).toEqual({
      start: "03:30",
      end: "07:00",
    });
  });
});

describe("isSendable", () => {
  it("takes a figure inside the api's own bounds", () => {
    expect(isSendable({ kind: "partial", blockId: "x", minutes: MIN_ACTUAL_MINUTES })).toBe(true);
    expect(isSendable({ kind: "partial", blockId: "x", minutes: MAX_ACTUAL_MINUTES })).toBe(true);
  });

  it("refuses a figure the api would reject", () => {
    expect(isSendable({ kind: "partial", blockId: "x", minutes: 0 })).toBe(false);
    expect(isSendable({ kind: "partial", blockId: "x", minutes: MAX_ACTUAL_MINUTES + 1 })).toBe(
      false,
    );
    expect(isSendable({ kind: "partial", blockId: "x", minutes: 12.5 })).toBe(false);
  });

  it("refuses an interval with an end the reader cleared", () => {
    expect(isSendable({ kind: "moved", blockId: "x", range: { start: "09:00", end: "" } })).toBe(
      false,
    );
    expect(
      isSendable({ kind: "moved", blockId: "x", range: { start: "9:00", end: "10:00" } }),
    ).toBe(false);
  });
});

describe("stateBody", () => {
  it("names the week and the state, and carries no figure", () => {
    expect(stateBody("skipped", ISO_WEEK)).toEqual({ isoWeek: ISO_WEEK, state: "skipped" });
  });

  it("sends nothing at all without a week to record against", () => {
    expect(stateBody("skipped", null)).toBeNull();
  });
});

describe("bodyFor", () => {
  it("sends a partial's minutes", () => {
    const form = { kind: "partial", blockId: BLOCK_LEETCODE, minutes: 145 } as const;

    expect(bodyFor(form, context)).toEqual({
      isoWeek: ISO_WEEK,
      state: "partial",
      actualMinutes: 145,
    });
  });

  it("resolves a moved interval to instants in the day's zone", () => {
    const form = {
      kind: "moved",
      blockId: BLOCK_LEETCODE,
      range: { start: "14:00", end: "15:30" },
    } as const;

    const body = bodyFor(form, context);

    expect(body?.state).toBe("moved");
    expect(body?.actualInterval).toEqual({
      start: "2026-02-09T14:00:00.000Z",
      end: "2026-02-09T15:30:00.000Z",
    });
  });

  /* A block that ran past midnight is ordinary, so an end at or before the start is the following date
     rather than a reversed interval the api would refuse. */
  it("puts an end at or before the start on the following date", () => {
    const form = {
      kind: "moved",
      blockId: BLOCK_LEETCODE,
      range: { start: "23:00", end: "06:00" },
    } as const;

    const body = bodyFor(form, context);

    expect(body?.actualInterval).toEqual({
      start: "2026-02-09T23:00:00.000Z",
      end: "2026-02-10T06:00:00.000Z",
    });
  });

  it("treats an end equal to the start as a full day rather than as no interval", () => {
    const form = {
      kind: "moved",
      blockId: BLOCK_LEETCODE,
      range: { start: "09:00", end: "09:00" },
    } as const;

    const body = bodyFor(form, context);
    const interval = body?.actualInterval ?? { start: "", end: "" };

    expect(Date.parse(interval.end) - Date.parse(interval.start)).toBe(24 * 60 * 60 * 1000);
  });

  /* The transition dates the domain states a rule for. A wall time in the spring gap resolves forward, and
     the interval the api stores is one the reader can read back at the same wall time either side of it. */
  it("resolves an interval across the spring transition under the domain's own rule", () => {
    const form = {
      kind: "moved",
      blockId: BLOCK_LEETCODE,
      range: { start: "00:30", end: "03:30" },
    } as const;

    const body = bodyFor(form, { date: "2026-03-29", zone: ZONE, isoWeek: "2026-W13" });
    const interval = body?.actualInterval ?? { start: "", end: "" };

    expect(clockIn(interval.start, ZONE)).toBe("00:30");
    expect(clockIn(interval.end, ZONE)).toBe("03:30");
    /* Two wall hours apart across a gap of one, which is what a 23-hour day means for a span inside it. */
    expect(Date.parse(interval.end) - Date.parse(interval.start)).toBe(2 * 60 * 60 * 1000);
  });

  it("sends nothing for a figure outside the api's bounds", () => {
    expect(bodyFor({ kind: "partial", blockId: "x", minutes: 0 }, context)).toBeNull();
  });

  it("sends nothing without a week to record against", () => {
    const form = { kind: "moved", blockId: "x", range: { start: "09:00", end: "10:00" } } as const;

    expect(bodyFor(form, { ...context, isoWeek: null })).toBeNull();
  });
});
