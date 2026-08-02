/* The quarter hour, and the constant that mirrors the token.
 *
 * The equality test is the mechanism, not a formality: TypeScript cannot read a custom property, so
 * `SNAP_MINUTES` is a second copy of `--snap` and the only thing standing between the two is this file. It is
 * the same shape as the theme's two breakpoint literals, which are pinned against the same token file. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { srcDir } from "../../testing/compileTheme";
import {
  RECORDED_STEP_MINUTES,
  SNAP_MINUTES,
  formatClock,
  parseClock,
  snapClock,
  snapMinutes,
} from "./quarterHour";

describe("SNAP_MINUTES", () => {
  it("equals the --snap token it mirrors", async () => {
    const layout = await readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");
    const token = /--snap:\s*(\d+)/.exec(layout);

    expect(token?.[1]).toBe(String(SNAP_MINUTES));
  });

  it("is not the recorded step, which is a measurement rather than a placement", () => {
    expect(RECORDED_STEP_MINUTES).toBe(5);
    expect(RECORDED_STEP_MINUTES).not.toBe(SNAP_MINUTES);
  });
});

describe("snapMinutes", () => {
  it.each([
    [0, 0],
    [7, 0],
    [8, 15],
    [22, 15],
    [23, 30],
    [50, 45],
    [52, 45],
    [53, 60],
    [60, 60],
  ])("snaps %i to %i at the quarter hour", (input, expected) => {
    expect(snapMinutes(input, SNAP_MINUTES)).toBe(expected);
  });

  it("rounds a half up, so a reader who types the midpoint moves forward", () => {
    expect(snapMinutes(7.5, SNAP_MINUTES)).toBe(15);
  });

  it("never returns a negative figure, whatever the caller subtracted", () => {
    expect(snapMinutes(-40, SNAP_MINUTES)).toBe(0);
  });

  it("snaps a recorded actual by five, which the ledger's common correction needs", () => {
    expect(snapMinutes(52, RECORDED_STEP_MINUTES)).toBe(50);
    expect(snapMinutes(53, RECORDED_STEP_MINUTES)).toBe(55);
  });
});

describe("parseClock", () => {
  it.each([
    ["00:00", 0],
    ["09:15", 555],
    ["23:45", 1425],
    ["9:15", 555],
  ])("reads %s as %i minutes", (text, minutes) => {
    expect(parseClock(text)).toBe(minutes);
  });

  it.each(["", "24:00", "09:60", "9", "09:1", "nine", "09:15:00"])(
    "refuses %s rather than guessing",
    (text) => {
      expect(parseClock(text)).toBeNull();
    },
  );
});

describe("formatClock", () => {
  it.each([
    [0, "00:00"],
    [555, "09:15"],
    [1425, "23:45"],
  ])("writes %i as %s, zero-padded so a column aligns", (minutes, text) => {
    expect(formatClock(minutes)).toBe(text);
  });
});

describe("snapClock", () => {
  it.each([
    ["09:07", "09:00"],
    ["09:08", "09:15"],
    ["13:22", "13:15"],
    ["13:23", "13:30"],
  ])("snaps %s to %s", (input, expected) => {
    expect(snapClock(input)).toBe(expected);
  });

  /* 23:53 would round to the next day. A time control's value is a clock time on the day the caller is
   * editing, so rolling it to 00:00 would silently move an interval to the day before, in a field showing four
   * characters. */
  it("clamps the last quarter of the day rather than rolling into the next one", () => {
    expect(snapClock("23:53")).toBe("23:45");
    expect(snapClock("23:59")).toBe("23:45");
  });

  it("hands back nothing for a value it cannot read, so a half-typed field is left alone", () => {
    expect(snapClock("13:")).toBeNull();
  });
});
