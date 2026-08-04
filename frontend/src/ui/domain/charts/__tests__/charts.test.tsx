/* THE CHARTS AS THEY RENDER, at the boundaries a chart actually meets.
 *
 * Every chart is exercised with an EMPTY series, a SINGLE-category series and a THIRTEEN-Area series where a
 * pigment repeats, because those are the three shapes that break a chart and the populated middle case is the one
 * that never does. A composition where `Unallocated` is the largest wedge has its own section: the largest wedge
 * on a real pie is frequently "nothing planned", which reads as a defect until it is labelled.
 *
 * WHAT IS ASSERTED STRUCTURALLY RATHER THAN VISUALLY. jsdom applies no stylesheet, so a rendered element says
 * nothing about what a rule declares. The claims that are about rules -- cobalt only, hatch always on, no motion
 * -- are read from `charts.css` and from the sources, and the claims that are about markup are read from the
 * rendering. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { parse } from "postcss";

import { refusalFor } from "../../../../../scripts/lib/declarations.ts";
import { declaredTokens } from "../../../../../scripts/lib/tokens.ts";
import { srcDir } from "../../../../testing/compileTheme";
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

const chartsDir = path.join(srcDir, "ui", "domain", "charts");
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

/** Every source in the family, comments and all, which is what a claim about a comment has to read. */
async function familySources(): Promise<{ name: string; text: string }[]> {
  const names = [
    "AreaLegend.tsx",
    "DataBar.tsx",
    "DeviationBar.tsx",
    "MaturityMeter.tsx",
    "PieChart.tsx",
    "StackedBars.tsx",
    "WedgePatterns.tsx",
    "deviation.ts",
    "hatch.ts",
    "index.ts",
    "paint.ts",
    "series.ts",
    "wedges.ts",
  ];
  return Promise.all(
    names.map(async (name) => ({
      name,
      text: await readFile(path.join(chartsDir, name), "utf8"),
    })),
  );
}

function chartsStylesheet(): Promise<string> {
  return readFile(path.join(chartsDir, "charts.css"), "utf8");
}

/** The declarations a rule set carries, keyed by selector, so a claim about an ink can name the rule. */
async function rulesInCharts(): Promise<Map<string, Map<string, string>>> {
  const rules = new Map<string, Map<string, string>>();
  parse(await chartsStylesheet()).walkRules((rule) => {
    const declarations = rules.get(rule.selector) ?? new Map<string, string>();
    rule.walkDecls((declaration) => {
      declarations.set(declaration.prop, declaration.value);
    });
    rules.set(rule.selector, declarations);
  });
  return rules;
}

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

  it("is painted with no step of the ramp, in the token that names the vacancy", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-ink--unallocated")?.get("--ai")).toBe("var(--unallocated)");
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

/* THERE IS NO LINE CHART IN THIS PRODUCT. The Area seal permits ink on a wedge or a bar fill, not on a line, and
 * twelve cobalt lines separated only by dash pattern is unreadable. An absence with no check is an absence that
 * comes back, so this is the check. */
describe("the line chart that does not exist", () => {
  it("is exported by nothing in the family", async () => {
    const barrel = await readFile(path.join(chartsDir, "index.ts"), "utf8");
    const exported = [...barrel.matchAll(/export \{([^}]*)\}/g)].flatMap((match) =>
      match[1].split(",").map((name) => name.trim()),
    );

    expect(exported.filter((name) => /line/i.test(name))).toEqual([]);
  });

  it("has no code path, because nothing here draws a line or a dash", async () => {
    for (const { name, text } of await familySources()) {
      expect(text, `${name} draws a polyline`).not.toMatch(/<polyline|<line\s+[^>]*points/);
      expect(text, `${name} names a line chart`).not.toMatch(/LineChart|lineChart/);
      expect(text, `${name} sets a dash pattern`).not.toContain("strokeDasharray");
    }
  });

  it("draws the trend with bar fills, which is the carrier the seal permits", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-fill")?.get("background-color")).toBe("var(--ai)");
    expect(rules.get(".chart-fill--hatched")?.get("background-image")).toBe("var(--hx)");
  });
});

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

  it("draws both directions in one ink, so the side is the whole encoding", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".deviation__bar")?.get("background")).toBe("var(--ink)");
    expect([...(rules.get(".deviation__bar--under") ?? [])]).toEqual([["right", "50%"]]);
    expect([...(rules.get(".deviation__bar--over") ?? [])]).toEqual([["left", "50%"]]);
  });

  /* COBALT ONLY, AND NO AREA INK ANYWHERE IN THE ROW, INCLUDING THE LABEL CELL. Read from the stylesheet as well
   * as from the rendering: a chip in the label cell would imply the bar could have been Area-coloured. */
  it("spends no Area ink anywhere, including the label cell", async () => {
    const { container } = render(
      <DeviationBar caption="Scheduled against target" format={hours} rows={rows} />,
    );

    for (const element of container.querySelectorAll("*")) {
      expect(element.className.toString()).not.toContain("chart-ink");
      expect(element.className.toString()).not.toContain("area-chip");
    }
    const deviationRules = [...(await rulesInCharts())].filter(([selector]) =>
      selector.startsWith(".deviation"),
    );
    expect(deviationRules.length).toBeGreaterThan(5);
    for (const [selector, declarations] of deviationRules) {
      for (const [property, value] of declarations) {
        expect(`${selector} ${property}`, `${selector} spends an Area ink`).not.toMatch(
          /--ai|--hx/,
        );
        expect(value, `${selector} spends an Area ink`).not.toMatch(/--area-|--ai\b|--hx\b/);
      }
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

  it("carries the chip without a texture, because one carrier per context", async () => {
    const rules = await rulesInCharts();

    expect(rules.has(".area-chip")).toBe(false);
    expect(rules.get(".chart-fill")?.has("background-image")).toBe(false);
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

  /* A bound of zero binds nothing, so there is nothing left to collect. The alternative reading, an empty run,
   * would report a parameter with no threshold as having collected none of it. */
  it("treats a bound of zero as nothing left to collect", () => {
    const { container } = render(<MaturityMeter value={0} bound={0} label="unbounded" />);

    expect(container.querySelectorAll(".meter__cell--empty")).toHaveLength(0);
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

  /* A COMMENT RECORDS WHY THE TWO DIFFER, so a later contributor does not unify them. Asserted rather than
   * trusted: the reason is what stops the next reader deleting one of the two forms. */
  it("each records why it is not the other, in the file a reader will open", async () => {
    const sources = new Map((await familySources()).map(({ name, text }) => [name, text]));

    expect(sources.get("MaturityMeter.tsx")).toContain("bounded");
    expect(sources.get("MaturityMeter.tsx")).toContain("DataBar");
    expect(sources.get("DataBar.tsx")).toContain("MaturityMeter");
    expect(sources.get("DataBar.tsx")).toContain("arbitrary magnitude");
  });
});

describe("the family's stylesheet", () => {
  /* MOTION IS ZERO, WITHOUT EXCEPTION, and the same list stylelint, the markup scan and the bundle gate read is
   * read here, so a property added to the design language reaches this test with no edit. */
  it("spends no property the design language bans", async () => {
    const offenders: string[] = [];
    parse(await chartsStylesheet()).walkDecls((declaration) => {
      const refusal = refusalFor(declaration.prop, declaration.value);
      if (refusal !== null) offenders.push(`${declaration.prop}: ${refusal}`);
    });

    expect(offenders).toEqual([]);
  });

  it("declares no keyframes, so there is nothing for a rule to reference", async () => {
    expect(await chartsStylesheet()).not.toContain("@keyframes");
  });

  it("states the hatch's lightening step once, from the token that declares it", async () => {
    const rules = await rulesInCharts();

    expect(rules.get(".chart-ink")?.get("color")).toBe(
      "color-mix(in srgb, var(--ai) var(--hatch-mix), var(--paper-raised))",
    );
    const spenders: string[] = [];
    parse(await chartsStylesheet()).walkDecls((declaration) => {
      if (declaration.value.includes("--hatch-mix")) spenders.push(declaration.prop);
    });
    expect(spenders).toEqual(["color"]);
  });

  /* THE TEXTURE'S INK IS `currentColor`, AND THAT IS THE ONLY MECHANISM THAT WORKS. A gradient declared in the
   * token layer resolves its own `var()`s against `:root`, so an element-level `--hatch-ink` cannot reach it: the
   * six textures computed to the empty string and every `background-image: var(--hatch-fwd)` computed to `none`
   * until `--hatch-ink` was declared. This is the check that keeps the chain intact from this end. */
  it("paints its texture with the ink the token layer resolves per element", async () => {
    const tokens = await declaredTokens();

    expect(tokens.get("--hatch-ink")).toBe("currentColor");
    for (const [name, value] of tokens) {
      if (!name.startsWith("--hatch-") || !value.includes("gradient(")) continue;
      for (const reference of value.matchAll(/var\((--[\w-]+)/g)) {
        expect(
          tokens.has(reference[1]),
          `${name} reads ${reference[1]}, which nothing declares`,
        ).toBe(true);
      }
    }
  });

  /* A HATCH NEVER SITS ON PAPER. It is a lighter step of its own fill and measures under 2:1 against either paper
   * surface, so a rule that painted a texture without an ink under it would put a near-invisible pattern straight
   * onto the page. */
  it("pairs every texture with an ink under it", async () => {
    const rules = await rulesInCharts();

    for (const [selector, declarations] of rules) {
      if (!declarations.has("background-image")) continue;
      const paired = rules.get(selector.replace("--hatched", ""));

      expect(
        paired?.get("background-color") ?? declarations.get("background-color"),
        `${selector} paints a texture with no ink under it`,
      ).toBe("var(--ai)");
    }
  });
});
