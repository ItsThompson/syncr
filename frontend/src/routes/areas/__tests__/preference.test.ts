/* How a preference reads in a cell, and what a draft of one sends.
 *
 * The two forms the ticket names, `05:30 or 13:15 · strong` and `morning · soft`, are one function over the
 * same data, so both are asserted from the same builder rather than from two. */

import { describe, expect, it } from "vitest";

import {
  DAYPARTS,
  NO_PREFERENCE,
  asClock,
  bodyOf,
  capRefusal,
  draftOf,
  preferenceCellText,
  windowPhrase,
  withAnotherWindow,
  withCap,
  withIdealDuration,
  withStrength,
  withWindow,
  withoutWindow,
} from "../preference";
import { buildNoPreference, buildPreference, CAREER } from "./fixtures";
import type { EffectivePreference } from "../../../api/hooks/usePreferences";

function effective(overrides: Partial<EffectivePreference> = {}): EffectivePreference {
  return { ...buildPreference().effective!, ...overrides };
}

describe("what a preference cell reads", () => {
  it("joins the windows' start times with the strength", () => {
    const text = preferenceCellText(
      effective({
        windows: [
          { start: "05:30:00", end: "07:00:00" },
          { start: "13:15:00", end: "14:45:00" },
        ],
        strength: "strong",
      }),
    );

    expect(text).toBe("05:30 or 13:15 \u00b7 strong");
  });

  it("names a window that is exactly a part of the day", () => {
    const text = preferenceCellText(
      effective({ windows: [{ start: "06:00:00", end: "12:00:00" }], strength: "soft" }),
    );

    expect(text).toBe("morning \u00b7 soft");
  });

  it("names every part of the day it has a word for, and nothing else", () => {
    const named = DAYPARTS.map((part) =>
      windowPhrase([{ start: `${part.start}:00`, end: `${part.end}:00` }]),
    );

    expect(named).toEqual(["morning", "afternoon", "evening"]);
  });

  it("reads a clock time rather than a name for a window a minute off a daypart", () => {
    /* An exact match rather than a classification: a tolerance would make two different preferences read
     * identically, which is worse than a clock time for the reader who authored one deliberately. */
    expect(windowPhrase([{ start: "06:15:00", end: "12:00:00" }])).toBe("06:15");
    expect(windowPhrase([{ start: "06:00:00", end: "12:15:00" }])).toBe("06:00");
  });

  it("says a preference names no time of day when it declares no window", () => {
    const text = preferenceCellText(effective({ windows: [], strength: "soft" }));

    expect(text).toBe("no preferred time \u00b7 soft");
  });

  it("reads a dash when neither the Area nor anything above it declares one", () => {
    expect(preferenceCellText(null)).toBe(NO_PREFERENCE);
    expect(preferenceCellText(undefined)).toBe(NO_PREFERENCE);
  });

  it("drops the seconds the wire carries, because a window is minute resolution", () => {
    expect(asClock("05:30:00")).toBe("05:30");
  });
});

describe("a draft of a preference", () => {
  it("opens on the Area's own declaration", () => {
    const draft = draftOf(buildPreference());

    expect(draft.windows.map((window) => window.start)).toEqual(["05:30"]);
    expect(draft.strength).toBe("strong");
    expect(draft.preferredDurationMinutes).toBe(90);
    expect(draft.maxPerDayMinutes).toBe("180");
  });

  it("opens empty and soft for an Area that has declared none", () => {
    const draft = draftOf(buildNoPreference(CAREER));

    expect(draft.windows).toEqual([]);
    expect(draft.strength).toBe("soft");
    expect(draft.preferredDurationMinutes).toBeNull();
    expect(draft.maxPerDayMinutes).toBe("");
  });

  it("gives every window an identity the wire does not carry", () => {
    /* Two windows a reader is midway through editing can hold identical bounds, so nothing in their values
     * identifies a row. The id is what keeps the caret in the field being typed into. */
    const draft = withAnotherWindow(draftOf(buildPreference()), "new-1");

    expect(new Set(draft.windows.map((window) => window.id)).size).toBe(2);
  });

  it("strips those identities on submit, because the api's window is two clock times", () => {
    const body = bodyOf(withAnotherWindow(draftOf(buildPreference()), "new-1"));

    expect(body.windows).toEqual([
      { start: "05:30", end: "07:00" },
      { start: "06:00", end: "12:00" },
    ]);
  });

  it("sends every field, because a preference is replaced wholly rather than merged", () => {
    const body = bodyOf(draftOf(buildPreference()));

    expect(Object.keys(body).toSorted()).toEqual([
      "maxPerDayMinutes",
      "preferredDurationMinutes",
      "strength",
      "windows",
    ]);
  });

  it("replaces one window's bounds and leaves the others alone", () => {
    const draft = withAnotherWindow(draftOf(buildPreference()), "new-1");
    const edited = withWindow(draft, "new-1", { start: "13:15", end: "14:45" });

    expect(bodyOf(edited).windows).toEqual([
      { start: "05:30", end: "07:00" },
      { start: "13:15", end: "14:45" },
    ]);
  });

  it("drops one window and can be emptied, because an empty list is a statement", () => {
    const draft = draftOf(buildPreference());
    const emptied = withoutWindow(draft, draft.windows[0].id);

    expect(bodyOf(emptied).windows).toEqual([]);
  });

  it("carries the strength, the ideal duration and the cap the reader chose", () => {
    const draft = withCap(
      withIdealDuration(withStrength(draftOf(buildPreference()), "soft"), null),
      "45",
    );

    expect(bodyOf(draft)).toMatchObject({
      strength: "soft",
      preferredDurationMinutes: null,
      maxPerDayMinutes: 45,
    });
  });

  it("holds the cap as the reader's own text, like every other figure field on this screen", () => {
    /* A number-shaped draft round-trips each keystroke through text, which swallows a trailing point as it is
     * typed. The two sibling forms hold text for that reason and this one did not. */
    const draft = withCap(draftOf(buildPreference()), "100.");

    expect(draft.maxPerDayMinutes).toBe("100.");
    expect(bodyOf(draft).maxPerDayMinutes).toBe(100);
  });

  it("refuses a cap that is not a figure rather than sending none", () => {
    /* `3,5` posted as null would drop a HARD constraint the reader typed, with a 200 and nothing said. */
    const draft = withCap(draftOf(buildPreference()), "1,5");

    expect(capRefusal(draft)).toContain("A daily cap is a number");
    expect(capRefusal(withCap(draft, "100"))).toBeNull();
    expect(capRefusal(withCap(draft, ""))).toBeNull();
  });
});
