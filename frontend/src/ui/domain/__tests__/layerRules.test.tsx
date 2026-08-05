/* THE DOMAIN LAYER'S OWN RULES, ASSERTED OVER ITS SOURCES AND ITS STYLESHEETS.
 *
 * The same four questions the primitives and layout layers answer, asked of a third directory through the readers
 * in `src/testing/layerRules.ts`. The answers differ per layer and that is the point: the primitives own the
 * overlay family's shadow, the layout layer spends no state at all, and this layer spends states on rows and
 * carries the palette's own overlay.
 *
 * Every component is also mounted, from the barrel rather than from a list beside it, so a component added to the
 * layer and not to this file has no case here and one of these tests names it. */

import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { parse } from "postcss";

import * as domain from "..";
import { componentNamesIn } from "../../../testing/kitExports";
import { appSourceRoot, componentsNaming } from "../../../testing/kitSources";
import { domainDir } from "../../../testing/kitStylesheets";
import {
  declaredClasses,
  forcedColorsCasualties,
  layerSources,
  layerStylesheets,
  stateRules,
} from "../../../testing/layerRules";
import { SCREENS } from "../shell/navigation";
import type { Notice } from "../notices";

const sheets = () => layerStylesheets(domainDir);

const NOTICE: Notice = {
  id: "ics-stale",
  volume: "panel",
  pigment: "amber",
  title: "A calendar feed is stale",
  detail: "The Uni timetable feed has not answered since Sunday.",
  unavailable: ["reading new anchors from that feed"],
  stillWorks: ["the anchors already read", "solving the week"],
  since: null,
  action: null,
  scope: null,
};

/* Rendered inside a router where a component draws a link, because a link outside one throws rather than
 * degrading, and the sidebar's rows are real links by design. */
const GRID_BLOCK: domain.GridBlock = {
  id: "b1",
  title: "Leetcode · Graphs",
  span: { startMin: 540, endMin: 570 },
  origin: "task",
  pigment: "01",
  areaName: "Career",
  isPinned: false,
};

const PLACEMENT: domain.Placement = {
  left: 0,
  right: 0,
  indentSteps: 0,
  layer: 0,
  overlapCount: null,
  isSplit: false,
};

const EXTENT: domain.Extent = { startMin: 360, endMin: 1320 };

const WEEK_DAY: domain.WeekDay = {
  date: "2026-02-09",
  zone: "Europe/London",
  startMs: Date.parse("2026-02-09T00:00:00Z"),
  minutes: 1440,
  blocks: [GRID_BLOCK],
  bands: [],
};

const READINGS: domain.StripReadings = {
  scheduledMinutes: 4848,
  discretionaryMinutes: 3126,
  unallocatedMinutes: 1104,
  blockCount: 91,
  planCurrency: "current",
};
const MOUNTED: Readonly<Record<string, () => ReactElement>> = {
  AreaChip: () => <domain.AreaChip name="Career" pigment="01" />,
  AreaLegend: () => (
    <domain.AreaLegend
      label="Share of discretionary time"
      entries={[{ id: "career", label: "Career", pigment: "01", figure: "14.2h" }]}
    />
  ),
  Block: () => (
    <domain.Block block={GRID_BLOCK} placement={{ topPx: 0, heightPx: 26, across: PLACEMENT }} />
  ),
  CommandPalette: () => (
    <domain.CommandPalette actions={[]} onSelect={vi.fn<(id: string) => void>()} />
  ),
  DataBar: () => <domain.DataBar value={3.5} max={6} label="3.5h, 58% of the leader" />,
  DayColumn: () => (
    <domain.DayColumn
      canvasHeightPx={626}
      day={WEEK_DAY}
      extent={EXTENT}
      label="MON 09"
      nowMin={null}
      pxPerMin={0.87}
    />
  ),
  DeviationBar: () => (
    <domain.DeviationBar
      caption="Scheduled against target"
      format={(magnitude) => `${magnitude.toFixed(1)}h`}
      rows={[{ id: "career", label: "Career", actual: 27.3, target: 30 }]}
    />
  ),
  EmptyState: () => <domain.EmptyState title="Nothing yet" detail="Press n to capture one." />,
  EmptyWeek: () => (
    <domain.EmptyWeek
      extendHorizonHref="/settings"
      onSolveNow={vi.fn<() => void>()}
      reason="outside_horizon"
      setupHref="/setup"
      statement="This week is beyond your 14-day planning horizon."
    />
  ),
  ErrorState: () => <domain.ErrorState title="Not read" detail="Your plan is unchanged." />,
  ForbiddenBand: () => (
    <domain.ForbiddenBand heightPx={40} label="recovery · Kontron Interview" topPx={10} />
  ),
  GlyphSlot: () => <domain.GlyphSlot isPinned />,
  GridLines: () => <domain.GridLines extent={EXTENT} pxPerMin={0.87} />,
  HelpOverlay: () => <domain.HelpOverlay />,
  KeyHint: () => <domain.KeyHint keys="j" />,
  LedgerRow: () => <domain.LedgerRow timeRange="10:00-10:30" duration="30m" title="Clean" />,
  MaturityMeter: () => (
    <domain.MaturityMeter value={14} bound={15} label="durationMultiplier unlock progress" />
  ),
  NoticeCard: () => <domain.NoticeCard notice={{ ...NOTICE, volume: "inline" }} />,
  NoticeMark: () => <domain.NoticeMark pigment="amber" />,
  NoticePanel: () => <domain.NoticePanel notice={NOTICE} />,
  NoticeStrip: () => <domain.NoticeStrip notice={{ ...NOTICE, volume: "banner" }} />,
  NowRule: () => <domain.NowRule topPx={321} />,
  PendingState: () => <domain.PendingState title="Solving" detail="The last plan is on screen." />,
  PieChart: () => (
    <domain.PieChart
      caption="Share of the 33.7h scheduled"
      slices={[{ id: "career", label: "Career", pigment: "01", minutes: 820 }]}
    />
  ),
  Plate: () => <domain.Plate name="astrolabe" />,
  ShellLayout: () => <domain.ShellLayout />,
  SidebarNav: () => <domain.SidebarNav screens={SCREENS} currentPath="/week" />,
  SidebarNavItem: () => <domain.SidebarNavItem screen={SCREENS[0]} isCurrent />,
  StackedBars: () => (
    <domain.StackedBars
      caption="Composition by week"
      bars={[
        {
          id: "w06",
          label: "W06",
          segments: [{ id: "career", label: "Career", pigment: "01", minutes: 820 }],
        },
      ]}
    />
  ),
  StatusSurface: () => <domain.StatusSurface kind="empty" title="Nothing yet" detail="Press n." />,
  SummaryStrip: () => <domain.SummaryStrip readings={READINGS} verdict={null} />,
  Table: () => (
    <domain.Table
      columns={[{ key: "title", header: "Task", cell: () => "Leetcode" }]}
      rows={[{ id: "1" }]}
      rowKey={(row: { id: string }) => row.id}
      caption="Open tasks"
    />
  ),
  TopBar: () => <domain.TopBar />,
  TimeAxis: () => (
    <domain.TimeAxis canvasHeightPx={626} extent={EXTENT} nowMin={null} pxPerMin={0.87} />
  ),
  WeekGrid: () => (
    <domain.WeekGrid
      days={[WEEK_DAY]}
      extent={EXTENT}
      labels={["MON 09"]}
      nowMs={null}
      visibleHours={12}
    />
  ),
  WedgePatterns: () => (
    <svg>
      <domain.WedgePatterns idPrefix="mount" pigments={["01", "unallocated"]} />
    </svg>
  ),
  WizardSteps: () => (
    <domain.WizardSteps
      steps={[{ id: "areas", label: "Declare your Areas", status: "current" }]}
      label="Setting up"
    />
  ),
  Wordmark: () => <domain.Wordmark />,
};

describe("every component the layer exports", () => {
  it.each(Object.keys(MOUNTED))("mounts: %s", (name) => {
    const { container, baseElement } = render(<MemoryRouter>{MOUNTED[name]()}</MemoryRouter>);

    // An overlay renders into a portal, so the container is empty until it opens: the document is the evidence.
    expect(container.firstElementChild ?? baseElement.firstElementChild).not.toBeNull();
  });

  it("is mounted here, so a component cannot join the barrel unrendered", () => {
    expect(Object.keys(MOUNTED).toSorted()).toEqual(componentNamesIn(domain));
  });

  it("takes no className, because variation is a named decision rather than a caller's utility", async () => {
    for (const { name, text } of await layerSources(domainDir)) {
      expect(text, `${name} declares a className prop`).not.toMatch(/className\??:/);
    }
  });
});

/* THE STATES THIS LAYER SPENDS ARE THE BLOCK'S, AND NOTHING ELSE'S.
 *
 * Every state channel a ROW needs is assigned in `ui/primitives/states.css`: a ledger row, a wizard step, a table
 * row and a palette row all COMPOSE `.state-row` rather than declaring a hover fill or a current row's rule of their
 * own, and the week grid's block composes it for the same two channels. What the block does own is the set section
 * 14's table deals to it and to nothing else in the product: the tier ladder, the two origin identities, the split
 * rule, the proposal's absence of fill, and the two states that share the left rule. Those cannot live in a shared
 * sheet, because nothing else in the kit has a tier or an origin.
 *
 * SO THE ASSERTION IS THE EXACT SET, bounded by the inventory of what may exist rather than by a vocabulary of what
 * may not. A sheet in this layer spending a state that is not the block's fails, and so does the block spending a
 * property its channel is not dealt. `check-channels` refuses a SECOND FILE assigning one of these pairs; this says
 * which file assigns them and which states exist at all.
 *
 * A pigment and a volume are not states: they are what the notice IS, like a title, so they are variant classes
 * rather than attributes. The same is true of a wizard step's status and of an Area's ramp step on a block. */
describe("the states the layer spends", () => {
  it("are the block's own, in the one sheet that draws a block", async () => {
    const spent = (await stateRules(domainDir)).map((rule) => `${rule.sheet} ${rule.state}`);

    expect([...new Set(spent)].toSorted()).toEqual([
      "week-grid/block.css [data-conflict]",
      'week-grid/block.css [data-origin="anchor"]',
      'week-grid/block.css [data-origin="frame"]',
      "week-grid/block.css [data-proposal]",
      "week-grid/block.css [data-selected]",
      "week-grid/block.css [data-split]",
      'week-grid/block.css [data-tier="compact"]',
      'week-grid/block.css [data-tier="hairline"]',
      "week-grid/grid.css [data-dragging]",
    ]);
  });

  /* EVERY STATE EXCEPT HOVER SURVIVES FORCED-COLORS MODE, because each pairs its fill with a rule, a border or a
   * glyph. THE FRAME'S RECESSED FILL IS THE SECOND EXCEPTION and it is named here rather than papered over with a
   * redundant border: what identifies a frame block when the OS drops every fill is its origin mark and its own
   * title, both of which are text and neither of which a stylesheet declares. Adding a border to this rule would
   * make the check pass and would distinguish nothing, which is the shape of a guard written to be satisfied. */
  it("lose only hover and the frame's recessed fill to forced colors", async () => {
    expect(await forcedColorsCasualties(domainDir)).toEqual([
      'week-grid/block.css [data-origin="frame"]',
    ]);
  });

  it("composes the kit's row states where a row needs them, rather than restating them", async () => {
    const rows = await componentsNaming("state-row", domainDir);

    expect(rows.toSorted()).toEqual([
      "ledger/LedgerRow.tsx",
      "shell/SidebarNavItem.tsx",
      "table/Table.tsx",
      "week-grid/Block.tsx",
      "wizard/WizardSteps.tsx",
    ]);
  });
});

describe("the layer's stylesheets", () => {
  it("carry no shadow of their own: the palette composes the overlay's", async () => {
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        expect(declaration.prop, `${name} declares a shadow`).not.toBe("box-shadow");
      });
    }
  });

  it("declare no focus ring, because the ring belongs to the surface it lands on", async () => {
    for (const { name, css } of await sheets()) {
      parse(css).walkDecls((declaration) => {
        expect(declaration.prop.startsWith("outline"), `${name} declares an outline`).toBe(false);
      });
    }
  });

  it("restate no colour, because a component reads tokens", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/#[0-9a-f]{3,8}\b/i);
      expect(`${name} ${css}`).not.toMatch(/\b(?:rgba?|hsla?|oklch)\s*\(/i);
    }
  });

  it("reach no layer 0 ramp step", async () => {
    for (const { name, css } of await sheets()) {
      expect(`${name} ${css}`).not.toMatch(/--(?:cobalt|cream|oxide|verdigris|amber)-\d/);
      expect(`${name} ${css}`).not.toMatch(/--pigment-area-/);
    }
  });

  it("declare more than one class, so the check below cannot pass on an empty list", async () => {
    expect((await declaredClasses(domainDir)).size).toBeGreaterThan(20);
  });

  it("ship no rule nothing names, read from the class lists the application writes", async () => {
    const declared = await declaredClasses(domainDir);
    const consumers = await Promise.all(
      [...declared.keys()].map((className) => componentsNaming(className, appSourceRoot)),
    );
    const dead = [...declared.entries()]
      .filter((_, index) => consumers[index].length === 0)
      .map(([className, sheet]) => `${sheet} declares .${className}, which nothing names`);

    expect(dead).toEqual([]);
  });
});
