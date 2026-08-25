/* THE CHARTS AS THEY RENDER, at the boundaries a chart actually meets.
 *
 * Every chart is exercised with an EMPTY series, a SINGLE-category series and a THIRTEEN-Area series where a
 * pigment repeats, because those are the three shapes that break a chart and the populated middle case is the one
 * that never does. A composition where `Unallocated` is the largest wedge has its own section: the largest wedge
 * on a real pie is frequently "nothing planned", which reads as a defect until it is labelled.
 *
 * NOTHING HERE READS THE STYLESHEET. jsdom applies no rule, so a rendered element says nothing about what a rule
 * declares: the claims that are about rules live in `stylesheet.test.ts` and the claims that are about markup live
 * here. The two questions are the seam this file is split on. */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { kitStylesheet } from "../../../../testing/kitStylesheets";
import { AREA_PIGMENTS } from "../../marks/pigment";
import { AreaLegend } from "../AreaLegend";
import { DataBar } from "../DataBar";
import { DeviationBar } from "../DeviationBar";
import { MaturityMeter } from "../MaturityMeter";
import { PieChart } from "../PieChart";
import { StackedBars } from "../StackedBars";
import { hatchFor } from "../hatch";
import { UNALLOCATED, type AreaQuantity } from "../series";
import { PIE } from "../wedges";

const hours = (magnitude: number) => `${magnitude.toFixed(1)}h`;

function quantity(label: string, minutes: number, pigment: AreaQuantity["pigment"]): AreaQuantity {
  return { id: label.toLowerCase(), label, pigment, minutes };
}

const CAREER = quantity("Career", 820, "01");
const STUDY = quantity("Study", 300, "05");
const VACANT = quantity("Unallocated", 1104, UNALLOCATED);

const week = (id: string, segments: readonly AreaQuantity[]) => ({ id, label: id, segments });

/** The composition that exhausts the ramp: twelve steps plus a thirteenth Area holding the first one again. */
const THIRTEEN: readonly AreaQuantity[] = [
  ...AREA_PIGMENTS.map((pigment, index) => quantity(`Area ${pigment}`, 60 + index, pigment)),
  quantity("Thirteenth", 200, AREA_PIGMENTS[0]),
];

function wedgesIn(container: HTMLElement): SVGPathElement[] {
  return [...container.querySelectorAll<SVGPathElement>("path.pie__wedge")];
}

function patternOf(container: HTMLElement, wedge: SVGPathElement): Element {
  const reference = /url\(#(.+)\)/.exec(wedge.getAttribute("fill") ?? "");
  if (reference === null) throw new Error("a wedge is not filled by a pattern");
  const pattern = container.querySelector(`#${reference[1]}`);
  if (pattern === null) throw new Error(`no pattern ${reference[1]} in the document`);
  return pattern;
}

describe("PieChart", () => {
  it("draws an SVG so each wedge can carry its own hatch", () => {
    const { container } = render(<PieChart slices={[CAREER, STUDY]} caption="Composition" />);
    const svg = container.querySelector("svg");

    expect(svg).not.toBeNull();
    expect(wedgesIn(container)).toHaveLength(2);
    for (const wedge of wedgesIn(container)) {
      expect(wedge.getAttribute("fill")).toMatch(/^url\(#.+\)$/);
    }
  });

  /* ONE USER UNIT IS ONE CSS PIXEL, which is what holds the hatch at the pitch the token layer declares. An svg
   * whose viewBox and size disagree scales its patterns, and the six textures stop separating at wedge scale. */
  it("sizes itself in the same units as its viewBox, so the hatch keeps its declared pitch", () => {
    const { container } = render(<PieChart slices={[CAREER]} caption="Composition" />);
    const svg = container.querySelector("svg");

    expect(svg?.getAttribute("viewBox")).toBe(
      `0 0 ${svg?.getAttribute("width")} ${svg?.getAttribute("height")}`,
    );
  });

  it("gives each wedge a pattern carrying that pigment's ink and its texture", () => {
    const { container } = render(<PieChart slices={[CAREER, STUDY]} caption="Composition" />);

    for (const wedge of wedgesIn(container)) {
      const pattern = patternOf(container, wedge);
      const ground = pattern.querySelector(".pie__hatch-ground");
      const texture = pattern.querySelector(".pie__hatch-line, .pie__hatch-dot");

      expect(ground?.getAttribute("class")).toContain("chart-ink--");
      expect(texture).not.toBeNull();
    }
  });

  /* HATCH IS ALWAYS ON. There is no prop, no toggle and no preference: the texture arrives with the pigment, so
   * a caller has nothing to switch off. */
  it("declares one pattern per pigment rather than one per wedge", () => {
    const { container } = render(<PieChart slices={THIRTEEN} caption="Composition" />);

    expect(wedgesIn(container)).toHaveLength(13);
    expect(container.querySelectorAll("pattern")).toHaveLength(12);
  });

  it("labels every wedge outside the circle, never on the fill", () => {
    const { container } = render(<PieChart slices={[CAREER, STUDY]} caption="Composition" />);
    const labels = [...container.querySelectorAll("text.pie__label")];

    expect(labels.map((label) => label.textContent)).toEqual(["Career", "Study"]);
    for (const label of labels) {
      const box = container.querySelector("svg");
      const centre = {
        x: Number(box?.getAttribute("width")) / 2,
        y: Number(box?.getAttribute("height")) / 2,
      };
      const away = Math.hypot(
        Number(label.getAttribute("x")) - centre.x,
        Number(label.getAttribute("y")) - centre.y,
      );

      expect(away).toBeGreaterThan(PIE.radius);
    }
  });

  it("draws one whole circle for a single category rather than a degenerate arc", () => {
    const { container } = render(<PieChart slices={[CAREER]} caption="Composition" />);

    expect(wedgesIn(container)).toHaveLength(1);
    expect(wedgesIn(container)[0].getAttribute("d")).not.toContain("L");
  });

  it("states an empty series instead of drawing an empty circle", () => {
    const { container } = render(<PieChart slices={[]} caption="Composition" />);

    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText(/no composition to draw/i)).toBeInTheDocument();
    expect(screen.getByText("Composition")).toBeInTheDocument();
  });

  it("says the same for a series whose every category holds zero", () => {
    render(<PieChart slices={[quantity("Career", 0, "01")]} caption="Composition" />);

    expect(screen.getByText(/no composition to draw/i)).toBeInTheDocument();
  });

  /* A BOUNDED LABEL KEEPS THE WHOLE NAME. The drawn text is bounded to the gutter the geometry reserves, so
   * the wedge's `<title>` carries the name in full; an unbounded label already is the whole name and gets no
   * title beside it. */
  it("carries the whole name on a bounded label's own title", () => {
    const LONG = "Career, interview preparation and the long game beyond it";
    const { container } = render(
      <PieChart slices={[quantity(LONG, 300, "01")]} caption="Composition" />,
    );
    const labels = [...container.querySelectorAll("text.pie__label")];

    expect(labels).toHaveLength(1);
    expect(labels[0].textContent).not.toBe(LONG);
    expect(labels[0].querySelector("title")?.textContent).toBe(LONG);
  });

  it("gives an unbounded label no title, since its drawn text is already the whole name", () => {
    const { container } = render(<PieChart slices={[CAREER]} caption="Composition" />);

    expect(container.querySelector("text.pie__label title")).toBeNull();
  });
});

describe("Unallocated", () => {
  const composition = [CAREER, STUDY, VACANT];

  /* THE LARGEST WEDGE IS FREQUENTLY "NOTHING PLANNED", which looks like a defect until it is labelled. So it is
   * labelled, it holds a wedge like any category, and it is not the paper showing through. */
  it("reads as a labelled category when it is the largest wedge", () => {
    const { container } = render(<PieChart slices={composition} caption="Composition" />);
    const wedges = wedgesIn(container);
    const largest = wedges.at(-1);

    expect(container.querySelector("text.pie__label:last-of-type")?.textContent).toBe(
      "Unallocated",
    );
    expect(largest?.getAttribute("fill")).toMatch(/unallocated\)$/);
    expect(
      patternOf(container, largest as SVGPathElement).querySelector(".pie__hatch-ground"),
    ).not.toBeNull();
  });

  /* NO FOURTH USE OF HATCH. The product's three are Area redundancy on a chart fill, an anchor's fill and a
   * forbidden window; the vacancy holds no Area, so there is no identity for a texture to be redundant about. */
  it("takes no hatch, because there is no Area for a texture to be redundant about", () => {
    const { container } = render(<PieChart slices={composition} caption="Composition" />);
    const vacant = patternOf(container, wedgesIn(container).at(-1) as SVGPathElement);

    expect(hatchFor(UNALLOCATED)).toBeNull();
    expect(vacant.querySelector(".pie__hatch-line, .pie__hatch-dot")).toBeNull();
  });

  it("takes a deviation row like any other category", () => {
    render(
      <DeviationBar
        caption="Scheduled against target"
        format={hours}
        rows={[
          { id: "career", label: "Career", actual: 27.3, target: 30 },
          { id: "unallocated", label: "Unallocated", actual: 35.3, target: 15 },
        ]}
      />,
    );

    expect(screen.getByText("Unallocated")).toBeInTheDocument();
    expect(screen.getByText(/^\+20\.3h$/)).toBeInTheDocument();
  });

  it("takes a legend row, because the ledger is where a figure is read", () => {
    render(
      <AreaLegend
        label="Share of discretionary time"
        entries={[
          { id: "unallocated", label: "Unallocated", pigment: UNALLOCATED, figure: "18.4h" },
        ]}
      />,
    );

    expect(screen.getByText("Unallocated")).toBeInTheDocument();
    expect(screen.getByText("18.4h")).toBeInTheDocument();
  });
});

describe("StackedBars", () => {
  it("renders one row per week, in Area ink and hatched", () => {
    const { container } = render(
      <StackedBars
        caption="Composition by week"
        bars={[week("W06", [CAREER, STUDY]), week("W07", [CAREER])]}
      />,
    );
    const segments = [...container.querySelectorAll(".stacked__segment")];

    expect(container.querySelectorAll(".stacked__row")).toHaveLength(2);
    expect(segments).toHaveLength(3);
    for (const segment of segments) {
      expect(segment.className).toContain("chart-fill--hatched");
      expect(segment.className).toMatch(/chart-hatch--(?:fwd|back|vert|horz|cross|dot)/);
    }
  });

  it("normalises each bar to its own total, so the reading is composition per week", () => {
    const { container } = render(
      <StackedBars caption="Composition by week" bars={[week("W06", [CAREER, STUDY])]} />,
    );
    const widths = [...container.querySelectorAll<HTMLElement>(".stacked__segment")].map(
      (segment) => Number.parseFloat(segment.style.width),
    );

    expect(widths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(100, 2);
  });

  it("states each bar's composition in words, because a trend has no legend column", () => {
    render(<StackedBars caption="Composition by week" bars={[week("W06", [CAREER, STUDY])]} />);

    expect(screen.getByRole("img", { name: "W06: Career 73%, Study 27%" })).toBeInTheDocument();
  });

  it("drops a segment holding nothing and keeps the bar", () => {
    const { container } = render(
      <StackedBars
        caption="Composition by week"
        bars={[week("W06", [CAREER, quantity("Study", 0, "05")])]}
      />,
    );

    expect(container.querySelectorAll(".stacked__segment")).toHaveLength(1);
  });

  it("states an empty series, and a week holding nothing is an empty series", () => {
    render(<StackedBars caption="Composition by week" bars={[]} />);
    expect(screen.getByText(/no trend to draw/i)).toBeInTheDocument();

    render(
      <StackedBars
        caption="Composition by week"
        bars={[week("W06", [quantity("Career", 0, "01")])]}
      />,
    );
    expect(screen.getAllByText(/no trend to draw/i)).toHaveLength(2);
  });

  it("carries a thirteen-Area week, where identity rests on the hatch and the name", () => {
    const { container } = render(
      <StackedBars caption="Composition by week" bars={[week("W06", THIRTEEN)]} />,
    );
    const segments = [...container.querySelectorAll(".stacked__segment")];
    const inks = new Set(segments.map((segment) => segment.className));

    expect(segments).toHaveLength(13);
    // Twelve distinct paintings for thirteen categories: the pair that shares one is separated by its name.
    expect(inks.size).toBe(12);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("Thirteenth");
  });
});

/* THERE IS NO LINE CHART IN THIS PRODUCT, and the whole of that check reads sources and rules rather than a
 * rendering, so it lives in `stylesheet.test.ts` beside the other claims of its kind. */
describe("DeviationBar", () => {
  const rows = [
    { id: "career", label: "Career", actual: 27.3, target: 30 },
    { id: "study", label: "Study", actual: 22, target: 20 },
    { id: "admin", label: "Admin", actual: 5, target: 5 },
  ];

  it("carries direction by side and by sign, never by hue", () => {
    const { container } = render(
      <DeviationBar caption="Scheduled against target" format={hours} rows={rows} />,
    );

    expect(container.querySelectorAll(".deviation__bar--under")).toHaveLength(1);
    expect(container.querySelectorAll(".deviation__bar--over")).toHaveLength(1);
    expect(screen.getByText(/^\u22122\.7h$/)).toBeInTheDocument();
    expect(screen.getByText(/^\+2\.0h$/)).toBeInTheDocument();
    // Exactly on target: no bar and no sign.
    expect(screen.getByText(/^0\.0h$/)).toBeInTheDocument();
    expect(container.querySelectorAll(".deviation__bar")).toHaveLength(2);
  });

  /* COBALT ONLY, AND NO AREA INK ANYWHERE IN THE ROW, INCLUDING THE LABEL CELL. The stylesheet half of this claim
   * is in `stylesheet.test.ts`; this is the half no rule can make, because a chip in the label cell is markup
   * rather than a declaration. */
  it("spends no Area ink anywhere, including the label cell", () => {
    const { container } = render(
      <DeviationBar caption="Scheduled against target" format={hours} rows={rows} />,
    );

    for (const element of container.querySelectorAll("*")) {
      expect(element.className.toString()).not.toContain("chart-ink");
      expect(element.className.toString()).not.toContain("area-chip");
    }
  });

  it("states the scale the bars were sized by, at both ends", () => {
    render(<DeviationBar caption="Scheduled against target" format={hours} rows={rows} />);

    expect(screen.getByText(/\u22122\.7h under target/)).toBeInTheDocument();
    expect(screen.getByText(/\+2\.7h over target/)).toBeInTheDocument();
  });

  it("states no scale when every row is exactly on target", () => {
    const { container } = render(
      <DeviationBar
        caption="Scheduled against target"
        format={hours}
        rows={[{ id: "admin", label: "Admin", actual: 5, target: 5 }]}
      />,
    );

    expect(container.querySelector(".deviation__axis")).toBeNull();
    expect(container.querySelectorAll(".deviation__row")).toHaveLength(1);
  });

  it("plots one row against itself, which is the whole track", () => {
    const { container } = render(
      <DeviationBar
        caption="Scheduled against target"
        format={hours}
        rows={[{ id: "career", label: "Career", actual: 0, target: 10 }]}
      />,
    );

    expect(container.querySelector<HTMLElement>(".deviation__bar--under")?.style.width).toBe("50%");
  });

  it("states an empty series instead of drawing a bare zero rule", () => {
    const { container } = render(
      <DeviationBar caption="Scheduled against target" format={hours} rows={[]} />,
    );

    expect(container.querySelector(".deviation__zero")).toBeNull();
    expect(screen.getByText(/nothing to compare/i)).toBeInTheDocument();
  });

  it("carries thirteen rows without an Area ink appearing", () => {
    const { container } = render(
      <DeviationBar
        caption="Scheduled against target"
        format={hours}
        rows={[
          ...AREA_PIGMENTS.map((pigment, index) => ({
            id: pigment,
            label: `Area ${pigment}`,
            actual: index,
            target: 6,
          })),
          { id: "unallocated", label: "Unallocated", actual: 35, target: 15 },
        ]}
      />,
    );

    expect(container.querySelectorAll(".deviation__row")).toHaveLength(13);
    expect(container.innerHTML).not.toContain("chart-ink");
  });
});

describe("AreaLegend", () => {
  const entries = [
    { id: "career", label: "Career", pigment: "01" as const, figure: "14.2h" },
    { id: "projects", label: "Projects", pigment: "03" as const, figure: "0.0h" },
  ];

  it("renders a chip, the Area's name and the figure", () => {
    const { container } = render(
      <AreaLegend label="Share of discretionary time" entries={entries} />,
    );

    expect(container.querySelectorAll(".area-chip")).toHaveLength(2);
    expect(screen.getByText("Career")).toBeInTheDocument();
    expect(screen.getByText("14.2h")).toBeInTheDocument();
  });

  /* THE CHIP IS NEVER SHOWN WITHOUT THE NAME, and the chip itself is decorative: announcing both would read the
   * category twice. */
  it("hides the chip from a screen reader, because the name beside it is the identity", () => {
    const { container } = render(
      <AreaLegend label="Share of discretionary time" entries={entries} />,
    );

    for (const chip of container.querySelectorAll(".area-chip")) {
      expect(chip.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("keeps a row for a category holding nothing, because that is what the ledger is for", () => {
    render(<AreaLegend label="Share of discretionary time" entries={entries} />);

    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("0.0h")).toBeInTheDocument();
  });

  it("renders nothing at all for an empty list rather than a labelled empty one", () => {
    const { container } = render(<AreaLegend label="Share of discretionary time" entries={[]} />);

    expect(container.firstChild).toBeNull();
  });
});

describe("the two bounded-progress forms", () => {
  it("draws a meter with block characters from the kit's own glyph table", async () => {
    const { container } = render(
      <MaturityMeter value={7} bound={14} label="durationMultiplier unlock progress" />,
    );
    const cells = [...container.querySelectorAll(".meter__cell")];
    const table = await kitStylesheet("glyphs.css");

    expect(cells).toHaveLength(14);
    expect(cells.filter((cell) => cell.className.includes("--empty"))).toHaveLength(7);
    expect(table).toContain('--glyph-meter-cell: "\\2588"');
    expect(table).toContain(".glyph--meter-cell {\n  --glyph: var(--glyph-meter-cell);\n}");
    for (const cell of cells) {
      expect(cell.className).toContain("glyph--meter-cell");
      expect(cell.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("reports the meter's bound to a screen reader, which a run of blocks cannot", () => {
    render(<MaturityMeter value={31} bound={100} label="objectiveWeights unlock progress" />);
    const meter = screen.getByRole("meter", { name: "objectiveWeights unlock progress" });

    expect(meter).toHaveAttribute("aria-valuenow", "31");
    expect(meter).toHaveAttribute("aria-valuemax", "100");
  });

  it("fills no cell at zero and every cell at the bound", () => {
    const { container: none } = render(<MaturityMeter value={0} bound={15} label="none" />);
    const { container: all } = render(<MaturityMeter value={15} bound={15} label="all" />);

    expect(none.querySelectorAll(".meter__cell--empty")).toHaveLength(14);
    expect(all.querySelectorAll(".meter__cell--empty")).toHaveLength(0);
  });

  it("clamps a value past its bound rather than drawing a fifteenth cell", () => {
    const { container } = render(<MaturityMeter value={40} bound={15} label="over" />);

    expect(container.querySelectorAll(".meter__cell")).toHaveLength(14);
    expect(container.querySelectorAll(".meter__cell--empty")).toHaveLength(0);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "15");
  });

  /* THE VISUAL AND THE ACCESSIBILITY TREE ARE DRIVEN BY ONE CLAMPED PAIR, so they cannot disagree. They did: the
   * raw numbers drew a complete run for a bound of zero while reporting "0 of 0", and a negative bound or value
   * put `aria-valuemax` and `aria-valuenow` outside `[min, max]`, which ARIA forbids. For a reader on a screen
   * reader the range IS the component, so every row below asserts the two readings agree AND that the range is
   * one ARIA permits. */
  it.each([
    { value: 7, bound: 14, full: 7, max: 14, now: 7 },
    { value: 40, bound: 15, full: 14, max: 15, now: 15 },
    { value: 0, bound: 15, full: 0, max: 15, now: 0 },
    { value: 5, bound: 0, full: 14, max: 1, now: 1 },
    { value: 0, bound: 0, full: 0, max: 1, now: 0 },
    { value: 5, bound: -5, full: 14, max: 1, now: 1 },
    { value: -3, bound: 15, full: 0, max: 15, now: 0 },
  ])("draws and reports the same fraction at value $value of bound $bound", (row) => {
    const { container } = render(
      <MaturityMeter value={row.value} bound={row.bound} label="agreement" />,
    );
    const meter = screen.getByRole("meter");
    const filled = 14 - container.querySelectorAll(".meter__cell--empty").length;
    const now = Number(meter.getAttribute("aria-valuenow"));
    const max = Number(meter.getAttribute("aria-valuemax"));
    const min = Number(meter.getAttribute("aria-valuemin"));

    expect(filled).toBe(row.full);
    expect(max).toBe(row.max);
    expect(now).toBe(row.now);
    // A range ARIA permits, and a value inside it.
    expect(max).toBeGreaterThan(min);
    expect(now).toBeGreaterThanOrEqual(min);
    expect(now).toBeLessThanOrEqual(max);
    // The two readings agree: the run a reader sees is the fraction a screen reader hears.
    expect(Math.round((now / max) * 14)).toBe(filled);
  });

  it("draws a ranked bar as one fill at a percentage width", () => {
    const { container } = render(<DataBar value={3.5} max={6} label="3.5h of the 6.0h leader" />);

    expect(container.querySelector<HTMLElement>(".ranked-bar__fill")?.style.width).toBe("58.33%");
    expect(container.querySelectorAll(".meter__cell")).toHaveLength(0);
    expect(screen.getByRole("img", { name: "3.5h of the 6.0h leader" })).toBeInTheDocument();
  });

  it("draws no width for a ranked bar with nothing to rank against", () => {
    const { container: zero } = render(<DataBar value={3} max={0} label="nothing to rank" />);
    const { container: empty } = render(<DataBar value={0} max={6} label="none of the leader" />);

    // jsdom serialises a percentage without its trailing zeros, which is what a browser's computed style does too.
    expect(zero.querySelector<HTMLElement>(".ranked-bar__fill")?.style.width).toBe("0%");
    expect(empty.querySelector<HTMLElement>(".ranked-bar__fill")?.style.width).toBe("0%");
  });

  it("fills the whole track for the leader, and no more for a value past it", () => {
    const { container } = render(<DataBar value={12} max={6} label="past the leader" />);

    expect(container.querySelector<HTMLElement>(".ranked-bar__fill")?.style.width).toBe("100%");
  });
});
