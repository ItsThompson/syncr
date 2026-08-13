/* WHAT A TRADEOFF ROW TELLS THE READER A CONCESSION RECOVERS.
 *
 * THE FIGURE IS A CEILING AND THE CONTRACT SAYS SO IN AS MANY WORDS. The api sizes what a concession recovers as an
 * upper bound on the movement approving it produces, and it measures three cases where the figure states more than
 * approving it delivers and none where it states less. The three cases below are those three, each built as the wire
 * shape it arrives in and named by the bound it carries, because a hedge that is honest about one of them and not
 * the other two is still a false reading on two thirds of the rows.
 *
 * THE BOUND IS READ OFF `openapi.json` RATHER THAN WRITTEN HERE, because the committed document is the contract and a
 * phrase written beside a test is a memory of it. Crossing the document against the rendered wording is what makes
 * the wire and the screen agree by assertion: a description that stops calling the figure a bound reddens here
 * instead of leaving the screen hedging against nothing.
 *
 * EVERY CASE ASSERTS THE RENDERED ROW rather than the narrowing's return value alone, because the claim is about what
 * a reader reads. The narrowing is asserted too, and separately: it is the one place both surfaces read, so a hedge
 * composed there is one a second surface cannot lose. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AREA_CAREER,
  AREA_FITNESS,
  TASK_ID,
  ZONE,
  buildShortfall,
  buildTradeoff,
  buildVerdict,
} from "./fixtures";
import { readingsIn } from "../readings";
import { panelVerdictOf } from "../verdict";
import { VerdictPanel, formatMinutes } from "../../../ui/domain";
import type { PanelVerdict, VerdictTradeoff } from "../../../ui/domain";
import type { components } from "../../../api/schema";

type Shortfall = components["schemas"]["ShortfallResponse"];
type Tradeoff = components["schemas"]["TradeoffResponse"];

const CONTEXT = readingsIn(
  ZONE,
  new Map([
    [AREA_CAREER, "Career"],
    [AREA_FITNESS, "Fitness"],
  ]),
);

/** The figure every case below is offered, and the reading it has on this screen. */
const MINUTES = 80;
const FIGURE = "1h20m";

// ---------------------------------------------------------------------------
// The contract, as a file rather than as a memory
// ---------------------------------------------------------------------------

/** The committed document every generated client is built from. */
const CONTRACT = path.resolve(import.meta.dirname, "..", "..", "..", "..", "openapi.json");

/** The half of the document this file reads. Narrow on purpose: nothing else here is crossed. */
interface ContractSchema {
  readonly properties?: Readonly<Record<string, { readonly description?: string }>>;
}

interface ContractDocument {
  readonly components: { readonly schemas: Readonly<Record<string, ContractSchema>> };
}

/** How the wire itself describes what a tradeoff recovers. */
function recoveryDescribedOnTheWire(): string {
  const schemas = (JSON.parse(readFileSync(CONTRACT, "utf8")) as ContractDocument).components
    .schemas;
  const schema: ContractSchema | undefined = schemas.TradeoffResponse;
  const described: string | undefined = schema?.properties?.deltaMinutes?.description;
  if (described === undefined) {
    throw new Error(`${CONTRACT} describes no deltaMinutes on TradeoffResponse`);
  }
  return described;
}

// ---------------------------------------------------------------------------
// The three bounds, each as the wire shape that carries it
// ---------------------------------------------------------------------------

interface BoundCase {
  /** The bound this case carries, in the words the enumeration measures it in. */
  readonly bound: string;
  readonly shortfall: Shortfall;
  readonly tradeoff: Tradeoff;
}

const THE_THREE_BOUNDS: readonly BoundCase[] = [
  {
    bound:
      "a breach against a deadline gap, where the gap falls by less than the floor gives up once that Area's earlier deadlines have claimed it",
    shortfall: buildShortfall({ kind: "deadline_capacity", honoring: ["Fitness floor 5h"] }),
    tradeoff: buildTradeoff({
      kind: "breach_floor",
      targetId: AREA_FITNESS,
      label: `Breach the Fitness floor by ${FIGURE}`,
      deltaMinutes: MINUTES,
    }),
  },
  {
    bound:
      "a demand naming several tasks, which has no per-task split, so dropping one of three is offered the whole gap",
    shortfall: buildShortfall({
      against: ["F&F Past Papers", "Kim's Game Project", "36 South Application"],
    }),
    tradeoff: buildTradeoff({
      kind: "drop_item",
      targetId: TASK_ID,
      label: "Drop Kim's Game Project this week",
      deltaMinutes: MINUTES,
    }),
  },
  {
    bound:
      "the task cap read from eligibility, which nets immovable placements only while the gap was computed from the demand, which nets every one",
    shortfall: buildShortfall(),
    tradeoff: buildTradeoff({ kind: "accept_partial", targetId: TASK_ID, deltaMinutes: MINUTES }),
  },
];

/** The verdict this screen composes from one wire tradeoff and the gap it answers. */
function narrowedVerdict(tradeoff: Tradeoff, shortfall: Shortfall): PanelVerdict {
  return panelVerdictOf(buildVerdict({ shortfalls: [shortfall], tradeoffs: [tradeoff] }), CONTEXT);
}

/** What the screen composes for that tradeoff, from the narrowing both surfaces read. */
function narrowed(tradeoff: Tradeoff, shortfall: Shortfall): VerdictTradeoff {
  const [first] = narrowedVerdict(tradeoff, shortfall).tradeoffs;
  if (first === undefined) throw new Error("the narrowing dropped the tradeoff it was given");
  return first;
}

/** The row a reader reads, rendered from that same narrowing. */
function rowRendered(tradeoff: Tradeoff, shortfall: Shortfall): HTMLElement {
  render(<VerdictPanel verdict={narrowedVerdict(tradeoff, shortfall)} />);
  return screen.getByText(tradeoff.label);
}

describe("what a row states a concession recovers", () => {
  it.each(THE_THREE_BOUNDS)(
    "tells the reader a ceiling and not a figure, for $bound",
    ({ shortfall, tradeoff }) => {
      const row = rowRendered(tradeoff, shortfall);

      expect(row).toHaveTextContent(`recovers up to ${FIGURE}`);
      /* The un-hedged form of the same figure, which no row may state: `recovers` is never followed by a number. */
      expect(row.textContent).not.toMatch(/recovers\s*\d/);
    },
  );

  it.each(THE_THREE_BOUNDS)(
    "carries the bound in the narrowing, not in the surface, for $bound",
    ({ shortfall, tradeoff }) => {
      const recovers = narrowed(tradeoff, shortfall).recovers;

      expect(recovers).toBe(`up to ${FIGURE}`);
      /* The bare reading of the same minutes, which is what a surface would have to hedge for itself. */
      expect(recovers).not.toBe(formatMinutes(MINUTES));
    },
  );

  it("says nothing at all about a recovery the enumerator could not size", () => {
    const unsized = buildTradeoff({ deltaMinutes: null });
    const shortfall = buildShortfall();

    expect(narrowed(unsized, shortfall).recovers).toBeNull();
    expect(rowRendered(unsized, shortfall).textContent).toBe(unsized.label);
  });
});

describe("the wire's own description of the figure", () => {
  it("calls it an upper bound, which is what the rendered wording hedges for", () => {
    const described = recoveryDescribedOnTheWire();

    expect(described).toMatch(/upper bound/i);
    expect(described).toMatch(/rather than an exact figure/i);
    /* The screen's half of the same agreement, so the two cannot drift apart silently. */
    expect(narrowed(buildTradeoff(), buildShortfall()).recovers).toBe(`up to ${FIGURE}`);
  });
});
