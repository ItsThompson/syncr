/* The pure arithmetic and the naming this screen does, asserted without a DOM.
 *
 * Every boundary a pie and an Area list have lives here, where it can be checked against a value rather than
 * against a rendering: no Areas, one, twelve, thirteen, a zero target, a floor, a negative figure, and wedges
 * that must tile the whole. */

import { describe, expect, it } from "vitest";

import { UNALLOCATED, areaPigment } from "../../../ui/domain";
import {
  VACANCY_LABEL,
  WEDGE_LABEL_CHARS,
  deviationRowsOf,
  hoursOf,
  keyOf,
  legendOf,
  namingOf,
  wedgeLabel,
  wedgesOf,
} from "../entries";
import {
  asFloor,
  asHours,
  asPercent,
  asPoints,
  asWeekLabel,
  asWholePercent,
  shareOf,
} from "../figures";
import { thisIsoWeek } from "../week";
import {
  CAREER,
  DISCRETIONARY_MINUTES,
  STUDY,
  buildArea,
  buildCategories,
  buildCategory,
  buildThirteenAreas,
} from "./fixtures";

const AREAS = [buildArea(), buildArea({ id: STUDY, name: "Study", pigmentIndex: 4 })];

/** An Area the review names and the Area list has not delivered yet. */
const RUNNING_ID = "99999999-9999-4999-8999-999999999999";

describe("a figure on this screen", () => {
  it("reads a minute count as hours to one decimal", () => {
    expect(asHours(1104)).toBe("18.4h");
  });

  it("spells a deviation in points rather than in percent, so nothing invites adding it to one", () => {
    expect(asPoints(3.42)).toBe("3.4pp");
    expect(asPercent(35.31)).toBe("35.3%");
  });

  it("rounds an authored share to the whole point it was authored in", () => {
    expect(asWholePercent(30)).toBe("30%");
    expect(asWholePercent(29.6)).toBe("30%");
  });

  it("reads a floor as hours and minutes, and a dash for an Area declaring none", () => {
    expect(asFloor(5)).toBe("5h 00m");
    expect(asFloor(5.25)).toBe("5h 15m");
    expect(asFloor(null)).toBe("\u2014");
  });

  it("labels a week by its number alone, because the trend is one quarter", () => {
    expect(asWeekLabel("2026-W07")).toBe("W07");
  });
});

describe("a share of discretionary time", () => {
  it("divides the minutes by the denominator the percentages are measured against", () => {
    expect(shareOf(1680, DISCRETIONARY_MINUTES)).toBe(25);
  });

  it("is nothing rather than a division by zero when the week holds no discretionary time", () => {
    expect(shareOf(600, 0)).toBe(0);
  });

  it("is nothing when the week holds no plan of record, so no figure claims a denominator", () => {
    expect(shareOf(600, null)).toBe(0);
  });
});

describe("naming a category", () => {
  it("paints an Area with the step the deal gave it", () => {
    expect(namingOf(buildCategory(), AREAS, 0)).toEqual({
      label: "Career",
      pigment: areaPigment(0),
    });
  });

  it("names the vacancy and gives it the pigment that holds no step of the ramp", () => {
    expect(namingOf(buildCategory({ areaId: null }), AREAS, 2)).toEqual({
      label: VACANCY_LABEL,
      pigment: UNALLOCATED,
    });
  });

  it("never paints an Area as the vacancy while its name is still in flight", () => {
    /* The categories and the names are two reads, so declaring an Area leaves one redraw where the review has
     * a row the list has no name for. Painting it with the vacancy's ink would say it holds no Area. */
    const naming = namingOf(buildCategory({ areaId: RUNNING_ID }), AREAS, 5);

    expect(naming.pigment).not.toBe(UNALLOCATED);
    expect(naming.label).toBe(RUNNING_ID.slice(0, 8));
  });

  it("keys the vacancy by one name, because exactly one row carries no Area", () => {
    expect(keyOf(buildCategory({ areaId: null }))).toBe(UNALLOCATED);
    expect(keyOf(buildCategory())).toBe(CAREER);
  });
});

describe("the wedges", () => {
  it("tile the denominator, because the vacancy is what no block covered", () => {
    const wedges = wedgesOf(buildCategories(), AREAS);
    const total = wedges.reduce((sum, wedge) => sum + wedge.minutes, 0);

    expect(total).toBe(DISCRETIONARY_MINUTES);
  });

  it("draw the vacancy last, so it closes the circle rather than splitting the Areas", () => {
    const wedges = wedgesOf(buildCategories(), AREAS);

    expect(wedges.at(-1)?.label).toBe(VACANCY_LABEL);
  });

  it("are nothing at all when the period holds no category", () => {
    expect(wedgesOf([], AREAS)).toEqual([]);
  });

  it("keep a category holding zero, so what the period did not hold is visible", () => {
    const wedges = wedgesOf([buildCategory({ actualMinutes: 0 })], AREAS);

    expect(wedges).toHaveLength(1);
    expect(wedges[0].minutes).toBe(0);
  });

  it("carry a negative figure through rather than clamping one the api never sends", () => {
    const wedges = wedgesOf([buildCategory({ actualMinutes: -60 })], AREAS);

    expect(wedges[0].minutes).toBe(-60);
  });

  it("give a thirteenth Area a row of its own, and the same ink as the first", () => {
    /* The deal wraps at twelve and the wire carries the step, so the thirteenth wedge is the first wedge's
     * ink and its own name is the whole of what separates them. Ticket 1201 carries that decision; this
     * asserts the collision rather than hiding it. */
    const { areas } = buildThirteenAreas();
    const categories = areas.map((area) => buildCategory({ areaId: area.id }));

    const wedges = wedgesOf(categories, areas);

    expect(wedges).toHaveLength(13);
    expect(wedges[12].pigment).toBe(wedges[0].pigment);
    expect(wedges[12].label).not.toBe(wedges[0].label);
  });

  it("give twelve Areas twelve distinct inks, which is the whole of the sealed ramp", () => {
    const { areas } = buildThirteenAreas();
    const twelve = areas.slice(0, 12);
    const wedges = wedgesOf(
      twelve.map((area) => buildCategory({ areaId: area.id })),
      twelve,
    );

    expect(new Set(wedges.map((wedge) => wedge.pigment)).size).toBe(12);
  });
});

describe("a wedge label", () => {
  /* Measured in Chrome at 1440 and at 1024: the pie's gutter holds 97px and the label face sets at 5.7px per
   * character, so a 57-character Area name ran 228px past the svg's own edge and painted over the panel's
   * border. An Area name may be sixty characters, so this is an ordinary declaration. */
  const LONG = "Career, interview preparation and the long game beyond it";

  it("leaves a name the gutter holds exactly as it is", () => {
    expect(wedgeLabel("Fitness")).toBe("Fitness");
    expect(wedgeLabel("a".repeat(WEDGE_LABEL_CHARS))).toBe("a".repeat(WEDGE_LABEL_CHARS));
  });

  it("bounds a name the gutter does not hold, in one glyph rather than three", () => {
    const bounded = wedgeLabel(LONG);

    expect(bounded.length).toBeLessThanOrEqual(WEDGE_LABEL_CHARS);
    expect(bounded.endsWith("\u2026")).toBe(true);
  });

  it("keeps two long names distinct where their heads differ", () => {
    expect(wedgeLabel("Career, interview prep")).not.toBe(wedgeLabel("Career, long game"));
  });

  it("is applied to the pie and never to the legend, which is where the name is carried", () => {
    const areas = [buildArea({ name: LONG })];
    const categories = [buildCategory()];

    expect(wedgesOf(categories, areas)[0].label).toBe(wedgeLabel(LONG));
    expect(legendOf(categories, areas, DISCRETIONARY_MINUTES)[0].label).toBe(LONG);
  });

  it("is not applied to a deviation row, whose label cell is HTML and wraps", () => {
    const areas = [buildArea({ name: LONG })];

    expect(deviationRowsOf([buildCategory()], areas, DISCRETIONARY_MINUTES)[0].label).toBe(LONG);
  });
});

describe("the legend", () => {
  it("pairs every category with its share of discretionary time", () => {
    const entries = legendOf(buildCategories(), AREAS, DISCRETIONARY_MINUTES);

    expect(entries.map((entry) => entry.figure)).toEqual(["16.3%", "11.0%", "72.8%"]);
  });

  it("names every entry, because a chip on its own identifies nothing", () => {
    const entries = legendOf(buildCategories(), AREAS, DISCRETIONARY_MINUTES);

    expect(entries.every((entry) => entry.label.length > 0)).toBe(true);
  });
});

describe("the deviation rows", () => {
  it("compare actual share against target share, in percentage points", () => {
    const rows = deviationRowsOf(buildCategories(), AREAS, DISCRETIONARY_MINUTES);

    expect(rows[0].label).toBe("Career");
    expect(rows[0].target).toBeCloseTo(60, 5);
    expect(rows[0].actual).toBeCloseTo(16.25, 5);
  });

  it("carry no pigment field at all, which is what makes the cobalt rule a typecheck", () => {
    const rows = deviationRowsOf(buildCategories(), AREAS, DISCRETIONARY_MINUTES);

    expect(rows.every((row) => !("pigment" in row))).toBe(true);
  });

  it("include the vacancy as a row like any Area", () => {
    const rows = deviationRowsOf(buildCategories(), AREAS, DISCRETIONARY_MINUTES);

    expect(rows.at(-1)?.label).toBe(VACANCY_LABEL);
  });

  it("leave out a category with no target, because there is nothing to compare against", () => {
    const rows = deviationRowsOf(
      [buildCategory({ targetMinutes: null }), buildCategory({ areaId: STUDY })],
      AREAS,
      DISCRETIONARY_MINUTES,
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("Study");
  });

  it("keep a row whose target is zero, because zero is a target", () => {
    const rows = deviationRowsOf(
      [buildCategory({ targetMinutes: 0 })],
      AREAS,
      DISCRETIONARY_MINUTES,
    );

    expect(rows).toHaveLength(1);
    expect(rows[0].target).toBe(0);
  });
});

describe("the hours a category held", () => {
  it("reads the category's own figure", () => {
    expect(hoursOf(buildCategory({ actualMinutes: 1104 }))).toBe("18.4h");
  });

  it("reads zero for an Area the period has no row for", () => {
    expect(hoursOf(undefined)).toBe("0.0h");
  });
});

describe("which ISO week a date falls in", () => {
  it("names the week the api reads, zero-padded", () => {
    expect(thisIsoWeek(new Date(2026, 1, 11))).toBe("2026-W07");
  });

  it("takes the ISO year from the week's Thursday, not from the date's own year", () => {
    /* 1 January 2027 is a Friday, so its week's Thursday is 31 December 2026: the ISO year is 2026 and the
     * week is its 53rd. Reading the year off the date would answer 2027-W53, which does not exist. */
    expect(thisIsoWeek(new Date(2027, 0, 1))).toBe("2026-W53");
    expect(thisIsoWeek(new Date(2025, 11, 29))).toBe("2026-W01");
  });

  it("puts a Sunday in the week that began on the Monday before it", () => {
    expect(thisIsoWeek(new Date(2026, 1, 15))).toBe("2026-W07");
    expect(thisIsoWeek(new Date(2026, 1, 16))).toBe("2026-W08");
  });
});
