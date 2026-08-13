/* THE DRAFT, THE FILTERS, AND THE REFUSALS, over the boundaries a capture surface has to hold.
 *
 * A CAPTURE SURFACE IS ADVERSARIAL, so the cases here are the boundaries rather than the happy path: a
 * whitespace-only title, a minimum chunk over the estimate and back under it, a deadline in the past, a deadline
 * on a day the reader's zone skips, and a refusal naming a member the form has no row for.
 *
 * THE DEFAULTS ARE ASSERTED AS THE API'S OWN, because the two-value capture is only true if every other member
 * arrives with one. The screen's test drives the same defaults over a real request, which is the other half. */

import { describe, expect, it } from "vitest";

import { ZONE } from "./fixtures";
import {
  bodyOf,
  deadlineInstantOf,
  draftFrom,
  isSubmittable,
  priorityOf,
  refusalsIn,
} from "../../../app/capture/draft";
import { captureRefusedNotice, refusalsFrom } from "../../../app/capture/refusals";
import {
  DEFAULT_FILTERS,
  EVERY,
  areaFilterOf,
  atRiskFilterOf,
  selectedValue,
  statusFilterOf,
} from "../filters";
import type { Problem } from "../../../contract";

/** A 422 with the members it refuses, in the api's own shape. */
function refusedWith(errors: { field: string; message: string }[]): Problem {
  return {
    type: "syncr:validation-failed",
    title: "Validation failed",
    status: 422,
    detail: "One or more members were refused.",
    errors,
  };
}

describe("the draft an opening starts on", () => {
  it("opens on the api's own documented defaults", () => {
    expect(draftFrom()).toEqual({
      title: "",
      areaId: "",
      estimateMinutes: 30,
      minChunkMinutes: 15,
      deadline: "",
      priority: "normal",
      splittable: true,
    });
  });

  it("opens on an Area where the caller names one, which is what a slot would do", () => {
    expect(draftFrom({ areaId: "area-1" }).areaId).toBe("area-1");
  });

  it("opens on the estimate the caller names, which for a slot is what fits it exactly", () => {
    expect(draftFrom({ areaId: "area-1", estimateMinutes: 90 })).toMatchObject({
      areaId: "area-1",
      estimateMinutes: 90,
      minChunkMinutes: 15,
    });
  });

  /* A PREFILL THAT ARRIVES ALREADY REFUSED IS WORSE THAN NO PREFILL. The default floor is fifteen minutes, so an
     estimate under one would open the form on the pair `refusalsIn` refuses, on a row nobody has touched, with the
     submit disabled and nothing the reader did to fix. */
  it("brings the minimum chunk down to an estimate that sits below the default floor", () => {
    const draft = draftFrom({ areaId: "area-1", estimateMinutes: 10 });

    expect(draft.minChunkMinutes).toBe(10);
    expect(refusalsIn({ ...draft, title: "one" })).toEqual({});
  });

  it("carries no preferred-time member, because a preferred time belongs to an Area", () => {
    expect(Object.keys(draftFrom())).not.toContain("preferredTimes");
    expect(Object.keys(draftFrom())).not.toContain("preferredTime");
  });

  /* THE WINDOW AN OPENING CARRIES IS NOT THE DRAFT'S, and this is the assertion that keeps it out: the request
     shape refuses an unknown member, so a window that reached the draft would be a 422 on every prefilled
     capture rather than a value quietly dropped. */
  it("carries no window either, even when the opening it started from named one", () => {
    const draft = draftFrom({
      areaId: "area-1",
      estimateMinutes: 60,
      preferredWindow: { from: "2026-02-11T14:00:00+00:00", to: "2026-02-11T15:00:00+00:00" },
    });

    expect(Object.keys(draft)).not.toContain("preferredWindow");
    expect(bodyOf({ ...draft, title: "one" }, null)).toEqual({
      areaId: "area-1",
      title: "one",
      estimateMinutes: 60,
      minChunkMinutes: 15,
      deadline: null,
      priority: "normal",
      splittable: true,
    });
  });
});

describe("what the form refuses", () => {
  it("refuses a missing title and a missing Area, which are the two required values", () => {
    const refusals = refusalsIn(draftFrom());

    expect(refusals.title).toContain("needs a title");
    expect(refusals.areaId).toContain("needs an Area");
    expect(isSubmittable(draftFrom())).toBe(false);
  });

  it("refuses a title of nothing but whitespace rather than trimming it into one", () => {
    const draft = { ...draftFrom({ areaId: "area-1" }), title: "   \t  " };

    expect(refusalsIn(draft).title).toContain("needs a title");
  });

  it("refuses a minimum chunk larger than the estimate, and says why", () => {
    const draft = { ...draftFrom({ areaId: "area-1" }), title: "one", minChunkMinutes: 60 };

    expect(refusalsIn(draft).minChunkMinutes).toContain("no placement could satisfy both");
    expect(isSubmittable(draft)).toBe(false);
  });

  it("accepts a minimum chunk equal to the estimate, which is one placement of the whole thing", () => {
    const draft = {
      ...draftFrom({ areaId: "area-1" }),
      title: "one",
      estimateMinutes: 60,
      minChunkMinutes: 60,
    };

    expect(refusalsIn(draft)).toEqual({});
    expect(isSubmittable(draft)).toBe(true);
  });
});

describe("the body it sends", () => {
  it("trims the title and sends every other member", () => {
    const draft = { ...draftFrom({ areaId: "area-1" }), title: "  Kontron take-home " };

    expect(bodyOf(draft, null)).toEqual({
      areaId: "area-1",
      title: "Kontron take-home",
      estimateMinutes: 30,
      minChunkMinutes: 15,
      deadline: null,
      priority: "normal",
      splittable: true,
    });
  });

  it("sends the deadline it was given, so the zone is resolved once and above it", () => {
    const draft = { ...draftFrom({ areaId: "area-1" }), title: "one" };

    expect(bodyOf(draft, "2026-02-13T23:59:00+00:00").deadline).toBe("2026-02-13T23:59:00+00:00");
  });
});

describe("the deadline a date names", () => {
  it("is the last minute of that local day, with the zone's own offset on it", () => {
    expect(deadlineInstantOf("2026-02-13", ZONE)).toBe("2026-02-13T23:59:00Z");
    expect(deadlineInstantOf("2026-07-13", ZONE)).toBe("2026-07-13T23:59:00+01:00");
  });

  it("is null when no date is chosen, which is the member's own default", () => {
    expect(deadlineInstantOf("", ZONE)).toBeNull();
  });

  /* A deadline in the PAST is a real value and is not refused: `US-TASK-03` reports an overdue task rather than
     preventing one, and the probe reads a passed deadline as zero capacity before it. */
  it("resolves a date already behind the reader, because an overdue task is reported and not refused", () => {
    expect(deadlineInstantOf("2020-01-02", ZONE)).toBe("2020-01-02T23:59:00Z");
  });

  /* The last minute of a day the zone skips forward through. Havana's spring transition happens AT midnight, so
     23:59 is unaffected there; the case that matters here is that a resolved instant is always a real one. */
  it("answers a real instant on a day its zone shifts", () => {
    const resolved = deadlineInstantOf("2026-03-08", "America/Havana");

    expect(resolved).not.toBeNull();
    expect(Number.isNaN(Date.parse(resolved ?? ""))).toBe(false);
  });

  it("is null for a zone the runtime does not know, rather than a deadline a day out", () => {
    expect(deadlineInstantOf("2026-02-13", "Not/AZone")).toBeNull();
  });
});

describe("a priority a control answered with", () => {
  it("takes the four the objective knows", () => {
    for (const priority of ["low", "normal", "high", "urgent"] as const) {
      expect(priorityOf(priority, "normal")).toBe(priority);
    }
  });

  it("keeps the one already held for anything else, which is what a cast would otherwise be", () => {
    expect(priorityOf("medium", "high")).toBe("high");
  });
});

describe("the filters", () => {
  it("opens on the open tasks, so completing a task removes its row", () => {
    expect(DEFAULT_FILTERS).toEqual({ status: "open" });
  });

  it("reads the absent filter as an omitted parameter rather than an empty one", () => {
    expect(areaFilterOf(EVERY)).toBeUndefined();
    expect(statusFilterOf(EVERY)).toBeUndefined();
    expect(atRiskFilterOf(EVERY)).toBeUndefined();
  });

  it("takes each status the api serves and refuses anything outside the vocabulary", () => {
    expect(statusFilterOf("open")).toBe("open");
    expect(statusFilterOf("completed")).toBe("completed");
    expect(statusFilterOf("dropped")).toBe("dropped");
    expect(statusFilterOf("paused")).toBeUndefined();
  });

  /* THREE VALUES RATHER THAN A BOOLEAN. The absent filter and `false` are two different questions: one asks for
     every row and the other asks for the rows this week's verdict does not name. */
  it("tells the absent standing filter from the one asking for the rest", () => {
    expect(atRiskFilterOf("true")).toBe(true);
    expect(atRiskFilterOf("false")).toBe(false);
    expect(atRiskFilterOf(EVERY)).toBeUndefined();
  });

  it("shows a filter that is not set as the named absent value", () => {
    expect(selectedValue(undefined)).toBe(EVERY);
    expect(selectedValue(false)).toBe("false");
    expect(selectedValue("open")).toBe("open");
  });
});

describe("a refusal the api answered with", () => {
  it("puts each field error on the row the api named", () => {
    const refusals = refusalsFrom(
      refusedWith([
        { field: "title", message: "is too long" },
        { field: "minChunkMinutes", message: "exceeds the estimate" },
      ]),
    );

    expect(refusals).toEqual({ title: "is too long", minChunkMinutes: "exceeds the estimate" });
  });

  it("leaves a member the form has no row for out of the rows and into the sentence", () => {
    const refused = refusedWith([{ field: "projectId", message: "belongs to another Area" }]);

    expect(refusalsFrom(refused)).toEqual({});
    expect(captureRefusedNotice(refused).detail).toContain("projectId belongs to another Area.");
  });

  it("has no refusals at all before anything has been refused", () => {
    expect(refusalsFrom(null)).toEqual({});
  });

  it("is amber and names what still works, because nothing is broken", () => {
    const notice = captureRefusedNotice(refusedWith([]));

    expect(notice.pigment).toBe("amber");
    expect(notice.volume).toBe("inline");
    expect(notice.stillWorks.length).toBeGreaterThan(0);
  });
});
