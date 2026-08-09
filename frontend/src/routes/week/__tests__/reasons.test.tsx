/* THE CLAUSE KINDS THE CONTRACT DECLARES, CROSSED AGAINST THE ROWS THE SCREEN RENDERS FOR THEM.
 *
 * NOTHING IN THE TYPE SYSTEM MAKES THE SWITCH COVER THE UNION. `reasonRowsOf` is declared to return a row per
 * clause, and a `kind` with no `case` returns `undefined` at runtime and draws nothing at all: the reader loses the
 * clause silently rather than seeing a fallback. So the rows are read here as possibly absent, which is what the
 * runtime can actually produce, and every kind the contract declares is asserted to have one.
 *
 * THE KIND LIST IS READ OFF `openapi.json` RATHER THAN WRITTEN HERE, because a list written beside a test is a
 * memory of the contract and the committed document is the contract. The list is the union's own members, which is
 * what a client narrows on, and the discriminator mapping is crossed against it by a test rather than by a check
 * that runs while this module loads: a widening that got half way would then be a collection error, and a suite that
 * did not run is not evidence about a guard.
 *
 * THE KEY SET IS COMPARED AT RUNTIME AS WELL AS BY THE COMPILER, and the two are not redundant. Keying the table
 * below on `ClauseKind` makes a kind added to the generated client a compile error, but vitest transpiles with
 * esbuild, which strips types without checking them, so that error is invisible to a test run and only
 * `tsc --noEmit` sees it. The runtime comparison is what makes a widening red in both. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DetailPanel } from "../components/DetailPanel";
import { definitionRowsOf, objectiveDeltaOf, reasonRowsOf } from "../reasons";
import { readingsIn } from "../readings";
import { AREA_CAREER, ZONE, buildBlock, buildReason, monday, span } from "./fixtures";
import type { LabelledRow } from "../../../ui/domain";
import type { components } from "../../../api/schema";

type Block = components["schemas"]["BlockResponse"];
type Clause = components["schemas"]["ClauseResponse"];
type ClauseKind = Clause["kind"];

const CONTEXT = readingsIn(ZONE, new Map([[AREA_CAREER, "Career"]]));

// ---------------------------------------------------------------------------
// The contract, as a file rather than as a memory
// ---------------------------------------------------------------------------

/** The committed document every generated client is built from. */
const CONTRACT = path.resolve(import.meta.dirname, "..", "..", "..", "..", "openapi.json");

/** The half of the document this file reads. Narrow on purpose: nothing else here is crossed. */
interface ContractProperty {
  readonly type?: string;
  readonly const?: string;
  readonly enum?: readonly string[];
}

interface ContractSchema {
  readonly oneOf?: readonly { readonly $ref: string }[];
  readonly discriminator?: {
    readonly propertyName: string;
    readonly mapping: Readonly<Record<string, string>>;
  };
  readonly properties?: Readonly<Record<string, ContractProperty>>;
}

interface ContractDocument {
  readonly components: { readonly schemas: Readonly<Record<string, ContractSchema>> };
}

const SCHEMAS = (JSON.parse(readFileSync(CONTRACT, "utf8")) as ContractDocument).components.schemas;

function schemaNamed(name: string): ContractSchema {
  const found: ContractSchema | undefined = SCHEMAS[name];
  if (found === undefined) throw new Error(`${CONTRACT} declares no schema named ${name}`);
  return found;
}

function propertyOf(schemaName: string, property: string): ContractProperty {
  const properties = schemaNamed(schemaName).properties;
  const found: ContractProperty | undefined =
    properties === undefined ? undefined : properties[property];
  if (found === undefined) throw new Error(`${schemaName} declares no ${property} property`);
  return found;
}

/** Every `kind` the union's own members declare, each read off that member's own schema. */
function kindsOfTheUnionMembers(): string[] {
  const members = schemaNamed("ClauseResponse").oneOf ?? [];
  return members.map((member) => {
    const name = member.$ref.split("/").at(-1) ?? member.$ref;
    const kind = propertyOf(name, "kind").const;
    if (kind === undefined) throw new Error(`${name} declares no kind to discriminate on`);
    return kind;
  });
}

/** Every `kind` the discriminator maps to a member. */
function kindsOfTheDiscriminator(): string[] {
  const discriminator = schemaNamed("ClauseResponse").discriminator;
  if (discriminator === undefined) throw new Error("ClauseResponse declares no discriminator");
  return Object.keys(discriminator.mapping);
}

/** The clause vocabulary: the union's own members, which is the set a generated client narrows on. */
const CLAUSE_KINDS: readonly string[] = kindsOfTheUnionMembers().toSorted();

// ---------------------------------------------------------------------------
// One clause of every kind, beside the row it renders as
// ---------------------------------------------------------------------------

interface ClauseCase {
  readonly clause: Clause;
  readonly row: LabelledRow;
}

/* `Record<ClauseKind, ...>` is what makes a kind added to the generated client a compile error here. The keys are
 * crossed against the document below, which is what makes it a red test as well. */
const EVERY_CLAUSE_KIND: Readonly<Record<ClauseKind, ClauseCase>> = {
  blocked: {
    clause: {
      kind: "blocked",
      window: span(monday("09:00"), monday("10:30")),
      rule: "anchor_overlap",
      detail: "Kontron Interview",
    },
    row: {
      label: "blocked",
      value: "Mon 09:00 to 10:30 \u00b7 anchor_overlap \u00b7 Kontron Interview",
    },
  },
  dominant: {
    clause: { kind: "dominant", term: "time_of_day_misfit", share: 0.4, baseline: null },
    row: { label: "dominant", value: "time_of_day_misfit \u00b7 40% of the plan's cost" },
  },
  bound: {
    clause: { kind: "bound", source: "routine", selected: "Sleep \u00b7 23:00 + 8h", cursor: null },
    row: { label: "bound", value: "Sleep \u00b7 23:00 + 8h" },
  },
  floor: {
    clause: { kind: "floor", areaId: AREA_CAREER, floorMinutes: 300, placed: 3, of: 4 },
    row: { label: "floor", value: "Career 5.0h \u00b7 3 of 4 occurrences placed" },
  },
  pinned: {
    clause: { kind: "pinned", at: span(monday("13:00"), monday("14:30")), pinnedOn: "2026-02-08" },
    row: {
      label: "pinned",
      value: "Mon 13:00 to 14:30 \u00b7 you moved it here on Sun 08 Feb",
    },
  },
  instead_of: {
    clause: {
      kind: "instead_of",
      placement: span(monday("09:00"), monday("10:30")),
      objectiveDelta: 0.18,
    },
    row: { label: "instead of", value: "Mon 09:00 to 10:30 \u00b7 what the solver proposed" },
  },
};

/* Read by kind as the DOCUMENT spells it rather than as this table is keyed, so a kind the contract declares and
 * this file does not build fails by name instead of quietly comparing one absence against another. */
const BY_KIND: Readonly<Record<string, ClauseCase>> = EVERY_CLAUSE_KIND;

function caseFor(kind: string): ClauseCase {
  const found: ClauseCase | undefined = BY_KIND[kind];
  if (found === undefined) throw new Error(`no clause is built here for the kind ${kind}`);
  return found;
}

function clauseOf(kind: string): Clause {
  return caseFor(kind).clause;
}

/** The rows the screen renders, read as the runtime can actually answer rather than as the type declares. */
function rowsOf(clauses: readonly Clause[]): readonly (LabelledRow | undefined)[] {
  return reasonRowsOf(buildReason([...clauses]), CONTEXT);
}

function rowRenderedFor(kind: string): LabelledRow | undefined {
  const [row] = rowsOf([clauseOf(kind)]);
  return row;
}

/** The labels of a rendered definition list, in the order it draws them. */
function labelsIn(list: HTMLElement): (string | null)[] {
  return [...list.querySelectorAll("dt")].map((term) => term.textContent);
}

describe("the clause vocabulary the contract declares", () => {
  it("discriminates on kind, and its members and its mapping name the same kinds", () => {
    expect(schemaNamed("ClauseResponse").discriminator?.propertyName).toBe("kind");
    expect(kindsOfTheUnionMembers().toSorted()).toEqual(kindsOfTheDiscriminator().toSorted());
  });

  it("is six kinds, and the generated client narrows on exactly those six", () => {
    expect(CLAUSE_KINDS).toHaveLength(6);
    expect(Object.keys(EVERY_CLAUSE_KIND).toSorted()).toEqual([...CLAUSE_KINDS].toSorted());
  });
});

describe("the row a clause renders as", () => {
  it.each(CLAUSE_KINDS)("is one labelled row for the %s clause, and never nothing", (kind) => {
    expect(rowRenderedFor(kind)).toEqual(caseFor(kind).row);
  });

  it("draws its label from a set that is exactly these six words", () => {
    const labels = CLAUSE_KINDS.map((kind) => rowRenderedFor(kind)?.label);

    expect(labels.toSorted()).toEqual([
      "blocked",
      "bound",
      "dominant",
      "floor",
      "instead of",
      "pinned",
    ]);
  });

  it("is one row per clause, in the order the record holds them", () => {
    /* The order is the record's own, which the api fixes before the wire, so a record built here in any other order
     * is what shows the mapping renders what it is given rather than an order of its own. */
    const rows = rowsOf([
      clauseOf("floor"),
      clauseOf("blocked"),
      clauseOf("pinned"),
      clauseOf("dominant"),
      clauseOf("instead_of"),
      clauseOf("bound"),
    ]);

    expect(rows.map((row) => row?.label)).toEqual([
      "floor",
      "blocked",
      "pinned",
      "dominant",
      "instead of",
      "bound",
    ]);
  });
});

describe("a dominant row's value", () => {
  /* The wire types `term` as a bare string, so the row can only render what the record carries. A display map would
   * be a second vocabulary of the seven objective term names, in a package that does not hold the first. */
  const TERMS = [
    "time_of_day_misfit",
    "budget_deviation",
    "context_switch",
    "a_term_no_display_map_could_hold",
  ];

  it.each(TERMS)("is %s verbatim, in the snake_case the objective spells it in", (term) => {
    const rendered = rowsOf([{ kind: "dominant", term, share: 0.4, baseline: null }])[0];

    expect(rendered?.value).toBe(`${term} \u00b7 40% of the plan's cost`);
    expect(rendered?.value).not.toMatch(/[a-z][A-Z]/);
  });

  it("carries the term verbatim where a baseline is measured too", () => {
    const rendered = rowsOf([
      {
        kind: "dominant",
        term: "churn",
        share: 0.4,
        baseline: {
          revisionId: "8c2d0e01-0000-4000-8000-000000000001",
          approvedAt: monday("09:00"),
        },
      },
    ])[0];

    expect(rendered?.value).toBe(
      "churn \u00b7 40% of the plan's cost \u00b7 against the revision approved Mon 09 Feb",
    );
  });

  it("has no closed vocabulary on the wire to be mapped from", () => {
    const term = propertyOf("DominantClause", "term");

    expect(term.type).toBe("string");
    expect(term.enum).toBeUndefined();
    expect(term.const).toBeUndefined();
  });
});

describe("the cost of a pin", () => {
  /* WHAT A WEIGHED PINNED BLOCK CARRIES. The pin contributes `pinned` and, where the solve had a placement to
   * supersede, `instead of`; the weighed clauses contribute `dominant` for the term carrying the plan's cost. The
   * two refusable kinds are absent because nothing refused a window and the Area declares no floor. */
  const THE_THREE_CLAUSES = [clauseOf("pinned"), clauseOf("instead_of"), clauseOf("dominant")];

  function blockPinnedAtACostOf(objectiveDelta: number | null): Block {
    return buildBlock({
      pinned: true,
      interval: span(monday("13:00"), monday("14:30")),
      supersededPlacement: span(monday("09:00"), monday("10:30")),
      objectiveDelta,
      reason: buildReason([...THE_THREE_CLAUSES]),
    });
  }

  function renderPanel(block: Block): HTMLElement {
    render(
      <DetailPanel
        cost={objectiveDeltaOf(block)}
        definitionRows={definitionRowsOf(block, CONTEXT)}
        onClose={() => undefined}
        reasonRows={reasonRowsOf(block.reason, CONTEXT)}
        title={block.title}
      />,
    );
    return screen.getByLabelText("Reason");
  }

  it("is no clause row: the mapping answers one row per clause and never a cost", () => {
    const rows = rowsOf(THE_THREE_CLAUSES);

    expect(rows.map((row) => row?.label)).toEqual(["pinned", "instead of", "dominant"]);
  });

  it("reaches the panel as one composed row beside the three clause rows", () => {
    const reason = renderPanel(blockPinnedAtACostOf(0.18));

    expect(labelsIn(reason)).toEqual(["pinned", "instead of", "dominant", "cost"]);
    expect(within(reason).getByText("+0.18 against the proposal")).toBeInTheDocument();
    /* The composed row lands among the clauses rather than among the block's own facts, which are their own list. */
    expect(labelsIn(screen.getByLabelText("Definition"))).toEqual([
      "when",
      "source",
      "type",
      "authority",
    ]);
  });

  it("is absent rather than composed where the block carries no delta", () => {
    const reason = renderPanel(blockPinnedAtACostOf(null));

    expect(labelsIn(reason)).toEqual(["pinned", "instead of", "dominant"]);
  });

  it("is read from the block rather than from the clause that records it", () => {
    /* The two figures agree in production, because both are written from the same pin. They disagree here only to
     * show which of them the composed row reads. */
    const block = blockPinnedAtACostOf(-0.42);

    expect(objectiveDeltaOf(block)).toBe("-0.42 against the proposal");
    expect(within(renderPanel(block)).getByText("-0.42 against the proposal")).toBeInTheDocument();
    /* No clause row states a delta at all, so the composed row is the only place one can come from. */
    const clauseValues = rowsOf(THE_THREE_CLAUSES).map((row) => row?.value);

    expect(clauseValues.join(" ")).not.toMatch(/[-+]?\d+\.\d+/);
  });
});
