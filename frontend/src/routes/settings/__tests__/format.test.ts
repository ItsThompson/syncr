/* Instants, spans, ages and durations as this screen states them.
 *
 * EVERY CASE NAMES A ZONE, because the rule under test is that this screen renders one zone at a time and never
 * the runtime's. A formatter that fell back to the host's zone would pass a test that did not say which zone it
 * expected. */

import { describe, expect, it } from "vitest";

import { NOT_YET, statedDuration, statedInstant, statedSpan } from "../format";

const LONDON = "Europe/London";

describe("an instant", () => {
  it("renders in the zone it was given, and in no other", () => {
    expect(statedInstant("2026-08-05T08:30:00Z", LONDON)).toBe("2026-08-05 \u00b7 09:30");
    expect(statedInstant("2026-08-05T08:30:00Z", "Asia/Kathmandu")).toBe("2026-08-05 \u00b7 14:15");
  });

  it("reads as never where the api reports nothing, in one spelling", () => {
    expect(statedInstant(null, LONDON)).toBe(NOT_YET);
    expect(statedInstant(undefined, LONDON)).toBe(NOT_YET);
  });

  /* An unreadable value is shown rather than swallowed: a reader seeing the raw string can report it, and a reader
   * seeing `never` would be told something false. */
  it("shows what it was given where it cannot be read", () => {
    expect(statedInstant("not an instant", LONDON)).toBe("not an instant");
    expect(statedInstant("2026-08-05T08:30:00Z", "Mars/Olympus")).toBe("2026-08-05T08:30:00Z");
  });
});

describe("a span", () => {
  it("renders both ends in the one zone", () => {
    expect(statedSpan("2026-08-07T13:00:00Z", "2026-08-10T08:00:00Z", LONDON)).toBe(
      "2026-08-07 \u00b7 14:00 to 2026-08-10 \u00b7 09:00",
    );
  });
});

describe("a duration", () => {
  it("is hours and minutes, dropping whichever is zero", () => {
    expect(statedDuration(450)).toBe("7h 30m");
    expect(statedDuration(480)).toBe("8h");
    expect(statedDuration(45)).toBe("45m");
    expect(statedDuration(0)).toBe("0m");
  });
});
