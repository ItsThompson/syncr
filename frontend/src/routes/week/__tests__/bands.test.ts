/* THE THREE KINDS OF GAP MAPPED ONTO ONE BAND, and the one thing that varies between them: the sentence in the
 * gutter.
 *
 * WHAT THESE CASES BOUND IS THAT NO WORDING IS COMPOSED HERE. One wording per empty-slot reason is
 * `syncr_domain.gaps`'s single statement, in Python, and the wire carries it rendered, so this module's whole job is
 * to carry it through. Every label driven here is therefore a string the server could not have produced: a
 * composition from the reason code would still have drawn something plausible, and only a label that could not have
 * been composed separates the two.
 *
 * THE IDENTIFIER IS ASSERTED BESIDE THE LABEL because it is not decoration either: `useWeekScreenInteraction` finds
 * a slot again by the pair the id spells, so a change to either half silently breaks activating the label. */

import { describe, expect, it } from "vitest";

import { bandOfEmptySlot, bandOfOffPlanPeriod, bandOfWindow } from "../bands";
import type { components } from "../../../api/schema";

type EmptySlot = components["schemas"]["EmptySlotResponse"];
type ForbiddenWindow = components["schemas"]["ForbiddenWindowResponse"];
type OffPlanPeriod = components["schemas"]["OffPlanPeriodResponse"];

const AREA_CAREER = "3f6b2c9d-1a77-4a1b-9a5f-8a2e4a1b9a5f";
const ANCHOR_ID = "5c9e0d4f-6a12-4f3a-8b21-7d2b1a904c71";

const START = "2026-02-11T14:00:00+00:00";
const END = "2026-02-11T15:00:00+00:00";

/** A wording no composition in this tree could arrive at, which is what makes the assertions below bite. */
const RENDERED = "a wording only the payload knows";

function slot(overrides: Partial<EmptySlot> = {}): EmptySlot {
  return {
    interval: { start: START, end: END },
    areaId: AREA_CAREER,
    reason: "no_eligible_content",
    label: RENDERED,
    ...overrides,
  };
}

function window(): ForbiddenWindow {
  return {
    interval: { start: START, end: END },
    kind: "recovery",
    scope: "all",
    forbiddenAreaIds: [],
    label: "recovery \u00b7 Kontron Interview",
    anchorId: ANCHOR_ID,
  };
}

function period(label: string | null): OffPlanPeriod {
  return { id: "off-plan-1", start: START, end: END, keepFrame: false, label };
}

describe("bandOfEmptySlot", () => {
  it("carries the wording the payload rendered, verbatim", () => {
    expect(bandOfEmptySlot(slot()).label).toBe(RENDERED);
  });

  it("carries the reason code beside it, so a reader keying on the code still has one", () => {
    expect(bandOfEmptySlot(slot()).reason).toBe("no_eligible_content");
  });

  /* THE NEWEST REASON TRAVELS LIKE THE REST. A dropped leg arrives as an ordinary empty slot whose reason names
   * the collision that caused it, so no branch here distinguishes it: the day renders whatever wording the payload
   * rendered, and widening `BandReason` without this case would still compile if the code were dropped. */
  it("carries a dropped leg's cause through as its reason", () => {
    expect(bandOfEmptySlot(slot({ reason: "dropped_leg" })).reason).toBe("dropped_leg");
  });

  /* THE WORDING IS NOT A FUNCTION OF THE REASON HERE. Two slots of one reason carrying two wordings draw two
   * different gutters: a lookup in this tree would collapse them onto one and pass every case above. */
  it("draws two wordings for one reason, because it reads the label and not the code", () => {
    const first = bandOfEmptySlot(slot({ label: "the first wording the payload sent" }));
    const second = bandOfEmptySlot(slot({ label: "the second wording the payload sent" }));

    expect(first.label).toBe("the first wording the payload sent");
    expect(second.label).toBe("the second wording the payload sent");
  });

  it("names the slot by the Area and the start that the interaction finds it again by", () => {
    expect(bandOfEmptySlot(slot()).id).toBe(`empty-slot:${AREA_CAREER}:${START}`);
  });

  it("takes its instants from the interval it was given", () => {
    const band = bandOfEmptySlot(slot());

    expect([band.startMs, band.endMs]).toEqual([Date.parse(START), Date.parse(END)]);
  });
});

describe("bandOfWindow", () => {
  it("carries the STORED label, so a retitled anchor cannot change what an approved week says", () => {
    expect(bandOfWindow(window()).label).toBe("recovery \u00b7 Kontron Interview");
  });

  it("reads the kind as the band's reason, which is the only thing the three gaps differ in", () => {
    expect(bandOfWindow(window()).reason).toBe("recovery");
  });
});

describe("bandOfOffPlanPeriod", () => {
  it("carries the user's own word for the span", () => {
    expect(bandOfOffPlanPeriod(period("Italy")).label).toBe("Italy");
  });

  it("carries null where they gave none, because a span needs no name to suspend scheduling", () => {
    expect(bandOfOffPlanPeriod(period(null)).label).toBeNull();
  });
});
