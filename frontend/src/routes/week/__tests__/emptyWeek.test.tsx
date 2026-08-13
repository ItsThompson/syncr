/* EVERY WORD THE CONTRACT CARRIES FOR A WEEK WITH NO PLAN, CROSSED AGAINST THE STATE THE SCREEN RENDERS FOR IT.
 *
 * THE WORD LIST IS READ OFF `openapi.json` RATHER THAN WRITTEN HERE, because a list written beside a test is a
 * memory of the contract and the committed document is the contract. A word the api can send and this screen has
 * no state for is invisible in a rendering: the reader gets a neighbouring state's heading over the server's
 * sentence, which is a heading contradicting its own body, and an assertion on either half alone stays green.
 *
 * DRIVEN THROUGH THE REAL ROUTE, so what is crossed is the payload's word against the rendered words. A component
 * test takes the word as a prop, so it can only reach the kit's own table; which word the kit is handed is the
 * screen's decision, and that is where one word can be collapsed into another.
 *
 * THE KEY SET IS COMPARED AT RUNTIME AS WELL AS BY THE COMPILER, and the two are not redundant. Keying the table on
 * the kit's own union makes a word it renders no state for a `tsc` error, and vitest transpiles with esbuild, which
 * strips types without checking them, so only the runtime comparison is red in a test run. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { cleanup, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt } from "../../../testing/renderRoute";
import {
  AWAITING_WEEK_FACTS,
  EMPTY_WEEK_FACTS,
  WEEK_PATH,
  buildWeekView,
  installWeekReads,
} from "./fixtures";
import type { EmptyWeekReason } from "../../../ui/domain";
import type { EmptyWeekFacts } from "../../../api/hooks/useWeek";

// ---------------------------------------------------------------------------
// The vocabulary, as a file rather than as a memory
// ---------------------------------------------------------------------------

/** The committed document every generated client is built from. */
const CONTRACT = path.resolve(import.meta.dirname, "..", "..", "..", "..", "openapi.json");

interface ContractDocument {
  readonly components: {
    readonly schemas: Readonly<Record<string, { readonly enum?: readonly string[] }>>;
  };
}

function wordsOfTheContract(): readonly string[] {
  const { schemas } = (JSON.parse(readFileSync(CONTRACT, "utf8")) as ContractDocument).components;
  const declared = schemas.EmptyReason?.enum;
  if (declared === undefined) throw new Error(`${CONTRACT} declares no EmptyReason vocabulary`);
  return declared;
}

const EMPTY_REASONS: readonly string[] = wordsOfTheContract();

// ---------------------------------------------------------------------------
// One week in every state, beside the state a reader gets
// ---------------------------------------------------------------------------

interface EmptyStateCase {
  /** The word the payload carries, typed, so the case is built from the vocabulary rather than from a string. */
  readonly reason: EmptyWeekReason;
  /** The payload's own facts for a week in this state. */
  readonly facts: EmptyWeekFacts;
  /** The heading, which is the screen's word for the state rather than the payload's sentence. */
  readonly title: string;
  /** Every repair the state offers, by the name it answers to and in the order they are drawn. */
  readonly offers: readonly string[];
}

/* `Record<EmptyWeekReason, ...>` is what makes a word the kit renders no state for a compile error here. The keys
 * are crossed against the document below, which is what makes it a red test as well. */
const EVERY_EMPTY_REASON: Readonly<Record<EmptyWeekReason, EmptyStateCase>> = {
  outside_horizon: {
    reason: "outside_horizon",
    facts: EMPTY_WEEK_FACTS,
    title: "This week is beyond your planning horizon",
    offers: ["Extend the horizon", "Solve this week now"],
  },
  setup_incomplete: {
    reason: "setup_incomplete",
    facts: {
      ...EMPTY_WEEK_FACTS,
      coversThisWeek: true,
      missingInputs: ["areas"],
      statement: "Declare at least one Area and a day shape for each weekday.",
    },
    title: "This week cannot be planned yet",
    offers: ["Finish setting up"],
  },
  /* The week whose plan has been asked for and not yet appended. Extending the horizon is absent because the
   * horizon already holds this week, so the offer would repair nothing and the heading above it would be false. */
  awaiting_maintainer: {
    reason: "awaiting_maintainer",
    facts: AWAITING_WEEK_FACTS,
    title: "syncr is planning this week",
    offers: ["Solve this week now"],
  },
};

/* Read by the word the DOCUMENT spells rather than as this table is keyed, so a word the contract carries and this
 * file does not build fails by name instead of quietly comparing one absence against another. */
const BY_REASON: Readonly<Record<string, EmptyStateCase>> = EVERY_EMPTY_REASON;

function caseFor(reason: string): EmptyStateCase {
  const found: EmptyStateCase | undefined = BY_REASON[reason];
  if (found === undefined) throw new Error(`no empty state is built here for the word ${reason}`);
  return found;
}

/** The week screen, on a week the api answers with no plan and the given word. */
async function openAPlanlessWeek(reason: string): Promise<HTMLElement> {
  const built = caseFor(reason);
  installWeekReads(
    buildWeekView({
      live: null,
      readings: null,
      emptyReason: built.reason,
      emptyWeek: built.facts,
    }),
  );
  const { container } = renderAt(WEEK_PATH);
  await waitFor(() => {
    expect(container.querySelector(".status__title")).not.toBeNull();
  });
  return container;
}

/** The heading a reader gets, read off the render rather than from the prop that fed it. */
function titleIn(container: HTMLElement): string {
  return container.querySelector(".status__title")?.textContent ?? "";
}

/** Every repair offered, in the order they are drawn, whether each is a link or a button. */
function offersIn(container: HTMLElement): string[] {
  return [...container.querySelectorAll(".status a, .status button")].map(
    (control) => control.textContent ?? "",
  );
}

describe("the words the contract carries for a week with no plan", () => {
  it("is three, and this screen renders a state for each of them", () => {
    expect(EMPTY_REASONS).toHaveLength(3);
    expect(Object.keys(EVERY_EMPTY_REASON).toSorted()).toEqual([...EMPTY_REASONS].toSorted());
    /* Each case installs the word it is keyed by, so a row cannot be asserted about another row's state. */
    for (const [word, built] of Object.entries(EVERY_EMPTY_REASON)) {
      expect(built.reason).toBe(word);
    }
  });

  it("draws a heading of its own for each state, so none can borrow its neighbour's", async () => {
    const drawn: string[] = [];
    for (const reason of EMPTY_REASONS) {
      // oxlint-disable-next-line no-await-in-loop -- one screen at a time: each state installs the reads it answers
      drawn.push(titleIn(await openAPlanlessWeek(reason)));
      cleanup();
    }

    expect(new Set(drawn).size).toBe(EMPTY_REASONS.length);
  });
});

describe("the state a word renders as", () => {
  it.each(EMPTY_REASONS)("heads %s with the title that word's own state has", async (reason) => {
    expect(titleIn(await openAPlanlessWeek(reason))).toBe(caseFor(reason).title);
  });

  it.each(EMPTY_REASONS)("offers %s its own repairs and no others", async (reason) => {
    expect(offersIn(await openAPlanlessWeek(reason))).toEqual(caseFor(reason).offers);
  });

  it.each(EMPTY_REASONS)(
    "draws the server's sentence for %s, not one of its own",
    async (reason) => {
      await openAPlanlessWeek(reason);

      expect(screen.getByText(caseFor(reason).facts.statement)).toBeInTheDocument();
    },
  );
});
