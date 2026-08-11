/* THE TABLE'S CLAIMS, AND WHERE EACH IS ASSERTED.
 *
 * The pitch and the cell size are the stylesheet's, so they are read from it: jsdom applies no stylesheet, and a
 * rendered assertion about a row's height would pass whether the rule exists or not. The sortable header, the
 * footer count and the column policy are behaviour, so they are exercised through the rendering.
 *
 * WHAT THE PITCH GUARANTEES IS A FLOOR, and no test in this file can measure a row: jsdom lays out nothing, so a
 * height read here is zero whatever the sheet says. What is holdable is the DECLARATION -- that nothing in the
 * family can truncate a cell instead of growing its row -- and the MARKUP the browser is handed. The sweep below
 * is the first and the column policy's cases are the second.
 *
 * THE SWEEP IS BOUNDED BY THE FAMILY'S FILES RATHER THAN BY A LIST OF THEM, because a list is a memory: a second
 * sheet added to this directory would be outside a list and is inside a read of the directory. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { parse } from "postcss";

import { codeWithoutComments } from "../../../../../scripts/lib/css-scan.ts";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { layerStylesheets } from "../../../../testing/layerRules";
import { Table, type TableColumn, type TableSort } from "../Table";

interface Task {
  readonly id: string;
  readonly title: string;
  readonly minutes: number;
}

const TASKS: readonly Task[] = [
  { id: "1", title: "Leetcode · Graphs", minutes: 90 },
  { id: "2", title: "36 South application", minutes: 45 },
  { id: "3", title: "Topic list questions", minutes: 60 },
];

const COLUMNS: readonly TableColumn<Task>[] = [
  { key: "title", header: "Task", cell: (task) => task.title, isSortable: true },
  {
    key: "minutes",
    header: "Estimate",
    measure: "figure",
    isSortable: true,
    cell: (task) => task.minutes,
  },
];

/* THE API'S CAP ON A NAME, READ OFF THE COMMITTED CONTRACT rather than written here, because a figure beside a
 * test is a memory of the contract and the document is the contract. The three requests that carry a name a reader
 * picks a row by are crossed against each other: a cap that moves on one of them is a finding here rather than a
 * fixture that quietly stops standing at the cap. */
const CONTRACT = path.resolve(import.meta.dirname, "..", "..", "..", "..", "..", "openapi.json");

const NAME_REQUESTS = ["AreaCreateRequest", "DayTypeCreateRequest", "TemplateCreateRequest"];

/** The half of the document this file reads. Narrow on purpose: nothing else here is crossed. */
interface ContractDocument {
  readonly components: {
    readonly schemas: Readonly<
      Record<
        string,
        | {
            readonly properties?: Readonly<
              Record<string, { readonly maxLength?: number } | undefined>
            >;
          }
        | undefined
      >
    >;
  };
}

function nameCapIn(file: string): number {
  const document = JSON.parse(readFileSync(file, "utf8")) as ContractDocument;
  const caps = NAME_REQUESTS.map(
    (schema) => document.components.schemas[schema]?.properties?.["name"]?.maxLength,
  );
  const [first] = caps;
  if (first === undefined || caps.some((cap) => cap !== first)) {
    throw new Error(`the contract caps ${NAME_REQUESTS.join(", ")} at ${JSON.stringify(caps)}`);
  }
  return first;
}

/** A name at that cap, which is longer than any column the product gives one. */
const NAME_AT_THE_CAP = "Weekday with lectures, a placement interview and a gym block";

function renderTable(props: Partial<Parameters<typeof Table<Task>>[0]> = {}) {
  const onSortChange = vi.fn<(next: TableSort) => void>();
  const result = render(
    <Table
      columns={COLUMNS}
      rows={TASKS}
      rowKey={(task) => task.id}
      caption="Open tasks"
      onSortChange={onSortChange}
      countLabel={(count) => `${count} open`}
      {...props}
    />,
  );
  return { onSortChange, ...result };
}

const stylesheet = () => kitStylesheet("table/table.css", domainDir);

/** The family's own sheets, read from the directory rather than from a list of their names. */
async function familySheets(): Promise<{ name: string; css: string }[]> {
  const inLayer = await layerStylesheets(domainDir);
  return inLayer
    .filter(({ name }) => name.startsWith(`table${path.sep}`))
    .map(({ name, css }) => ({ name, css: codeWithoutComments(css) }));
}

/** Every declaration the family's sheets make, with the sheet and the rule each sits in. */
async function familyDeclarations(): Promise<string[]> {
  const found: string[] = [];
  for (const { name, css } of await familySheets()) {
    parse(css).walkDecls((declaration) => {
      const selector = declaration.parent?.toString().split("{")[0].trim() ?? "";
      found.push(`${name} ${selector} ${declaration.prop}: ${declaration.value}`);
    });
  }
  return found;
}

/** The declared value of one property of one rule, as the sheet writes it. */
async function declaredValue(selector: string, property: string): Promise<string | null> {
  let value: string | null = null;
  parse(await stylesheet()).walkRules((rule) => {
    if (rule.selector !== selector) return;
    rule.walkDecls((each) => {
      if (each.prop === property) value = each.value;
    });
  });
  return value;
}

/* The widths are read from the style ATTRIBUTE. jsdom's style object drops a value its parser does not understand,
 * and `calc()` over mixed units is exactly such a value, so reading `style.width` would report an empty string for
 * a correct expression and pass a case that declared nothing at all. */
const widthsIn = (container: HTMLElement): (string | null)[] =>
  [...container.querySelectorAll("col")].map((col) => col.getAttribute("style"));

describe("the table's rows", () => {
  it("are named by a caption a screen reader reads before them", () => {
    renderTable();

    expect(screen.getByRole("table", { name: "Open tasks" })).toBeInTheDocument();
  });

  it("render every row the caller passed, in the order it passed them", () => {
    const { container } = renderTable();
    const cells = [...container.querySelectorAll("tbody td")].map((cell) => cell.textContent);

    expect(cells).toEqual([
      "Leetcode · Graphs",
      "90",
      "36 South application",
      "45",
      "Topic list questions",
      "60",
    ]);
  });

  it("pitch at --h-row with cells at --fs-data, which is the step for numbers you compare", async () => {
    const css = await stylesheet();

    expect(/\.table__row\s*\{[^}]*height:\s*var\(--h-row\)/.test(css)).toBe(true);
    expect(/\.table\s*\{[^}]*font-size:\s*var\(--fs-data\)/.test(css)).toBe(true);
  });

  it("set their figures tabular, so a column of them lines up", async () => {
    const css = await stylesheet();

    expect(/\.table\s*\{[^}]*font-variant-numeric:\s*tabular-nums/.test(css)).toBe(true);
  });

  it("right-align a figure column and leave a text column alone", () => {
    renderTable();
    const [title, estimate] = screen.getAllByRole("columnheader");

    expect(title).not.toHaveClass("table__header--figure");
    expect(estimate).toHaveClass("table__header--figure");
  });
});

describe("the sortable header", () => {
  it("is a control rather than a click handler on a cell, so a keyboard reaches it", () => {
    renderTable();

    expect(screen.getByRole("button", { name: /Task/ })).toBeInTheDocument();
  });

  it("asks for the column ascending when the rows are ordered by another", async () => {
    const { onSortChange } = renderTable({ sort: { key: "minutes", direction: "ascending" } });

    await userEvent.click(screen.getByRole("button", { name: /Task/ }));

    expect(onSortChange).toHaveBeenCalledWith({ key: "title", direction: "ascending" });
  });

  it("reverses the column the rows are already ordered by", async () => {
    const { onSortChange } = renderTable({ sort: { key: "title", direction: "ascending" } });

    await userEvent.click(screen.getByRole("button", { name: /Task/ }));

    expect(onSortChange).toHaveBeenCalledWith({ key: "title", direction: "descending" });
  });

  /* `aria-sort` sits on the column the rows are ACTUALLY ordered by. Announcing it on the column a reader last
   * pressed while the rows run by another tells a screen reader something the table does not do. */
  it("announces the order on the ordered column, and none on the others", () => {
    renderTable({ sort: { key: "minutes", direction: "descending" } });
    const [title, estimate] = screen.getAllByRole("columnheader");

    expect(estimate).toHaveAttribute("aria-sort", "descending");
    expect(title).toHaveAttribute("aria-sort", "none");
  });

  it("draws the direction as a mark rather than as colour alone", () => {
    const { container } = renderTable({ sort: { key: "minutes", direction: "ascending" } });

    expect(container.querySelector(".table__direction.glyph--triangle-up")).not.toBeNull();
  });

  it("is inert without a handler, because a header that reports nowhere is a decoration", () => {
    renderTable({ onSortChange: undefined });

    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("columnheader")[0]).not.toHaveAttribute("aria-sort");
  });
});

describe("the footer count", () => {
  it("is summed from the rows rendered, so the table cannot disagree with itself", () => {
    renderTable();

    expect(screen.getByText("3 open")).toBeInTheDocument();
  });

  it("is absent when the caller has no sentence to write", () => {
    const { container } = renderTable({ countLabel: undefined });

    expect(container.querySelector("tfoot")).toBeNull();
  });
});

/* THE COLUMN POLICY, THROUGH THE COMPONENT RATHER THAN THROUGH THE FUNCTION THAT COMPUTES IT.
 *
 * `columnWidths.test.ts` holds the arithmetic. What is here is the composition a browser is actually handed: which
 * element carries the width, whether the class that fixes the layout arrives with it, and -- the position that can
 * be off by one -- whether a `<col>` lands on the column that declared it when the standing column shifts every
 * data column one place to the right. */
describe("the column policy", () => {
  const WIDE: readonly TableColumn<Task>[] = [
    { key: "title", header: "Task", width: { weight: 1 }, cell: (task) => task.title },
    { key: "minutes", header: "Estimate", width: "88px", cell: (task) => task.minutes },
  ];

  it("leaves a table whose columns declare nothing laid out from its content, as it is today", () => {
    const { container } = renderTable();

    expect(container.querySelector("colgroup")).toBeNull();
    expect(screen.getByRole("table")).not.toHaveClass("table--fixed");
  });

  it("fixes the layout as soon as one column declares a width, because nothing else honours one", () => {
    const { container } = renderTable({ columns: WIDE });

    expect(container.querySelector("colgroup")).not.toBeNull();
    expect(screen.getByRole("table")).toHaveClass("table--fixed");
  });

  it("gives each column its own col, in the order the caller declared them", () => {
    const { container } = renderTable({ columns: WIDE });

    expect(widthsIn(container)).toEqual(["width: calc(100% - (88px));", "width: 88px;"]);
  });

  /* The standing column is drawn first, so every data column sits one place to the right of the position its own
   * declaration would suggest. A colgroup one entry short puts each width on its neighbour. */
  it("draws a col for the standing column too, so a width lands on the column that declared it", () => {
    const { container } = renderTable({
      columns: WIDE,
      standing: () => ({ isOverdue: true }),
    });

    expect(widthsIn(container)).toEqual([
      null,
      "width: calc(100% - (var(--table-mark-w) + 88px));",
      "width: 88px;",
    ]);
    expect(container.querySelectorAll("col")).toHaveLength(
      container.querySelectorAll("thead th").length,
    );
  });

  it("nets the surplus of the standing column's reserved width only when one is drawn", () => {
    const { container } = renderTable({ columns: WIDE });
    const widths = widthsIn(container);

    expect(widths).toHaveLength(WIDE.length);
    expect(widths.join(" ")).not.toContain("--table-mark-w");
  });

  /* A declaration is not measured against anything: `columnWidthsOf` is handed the widths and never the rows. What
   * this pins is that the component keeps it that way -- that no row content reaches the expression a `<col>`
   * carries. The RENDERED consequence, that the column beside a long cell holds its width, is a browser's and
   * `probe/table.probe.test.tsx` measures it. */
  it("emits the same widths whatever the rows hold, because a declaration is not measured against content", () => {
    const short = renderTable({ columns: WIDE });
    const long = renderTable({
      columns: WIDE,
      rows: [{ id: "1", title: NAME_AT_THE_CAP, minutes: 90 }],
    });

    expect(widthsIn(long.container)).toEqual(widthsIn(short.container));
    expect(widthsIn(long.container)).toEqual(["width: calc(100% - (88px));", "width: 88px;"]);
  });
});

/* NOTHING IN THE FAMILY TRUNCATES A CELL, REFUSED BY PROPERTY NAME OVER EVERY SHEET IN THE DIRECTORY.
 *
 * The four properties are refused together because each draws the same thing by a different route:
 * `text-overflow` needs `white-space: nowrap` to bite, `line-clamp` is `max-lines` plus `block-ellipsis` in one
 * shorthand and neither of the first two governs it, and `block-ellipsis` is the shorthand's own half. Refusing
 * one and reading the others as covered is how an end-ellipsis shipped on the week grid.
 *
 * READ OVER THE CODE WITH THE PROSE BLANKED, so a property named in a comment -- including in the comment above --
 * cannot answer the question, and read over every sheet rather than one rule, because a clamp reaching a cell
 * through a descendant selector draws the same ellipsis. */
describe("a cell wraps and never truncates", () => {
  const TRUNCATING = /line-clamp|block-ellipsis|text-overflow|white-space/;

  it("names no clamp and no ellipsis anywhere in the family", async () => {
    const truncating = (await familyDeclarations()).filter((each) => TRUNCATING.test(each));

    expect(truncating).toEqual([]);
  });

  it("read a family that exists, so the sweep above cannot pass on an empty read", async () => {
    const sheets = await familySheets();

    expect(sheets.map(({ name }) => name)).toContain(path.join("table", "table.css"));
    expect((await familyDeclarations()).length).toBeGreaterThan(20);
  });

  it("breaks a word longer than its column rather than drawing it over the column beside it", async () => {
    expect(await declaredValue(".table__cell", "overflow-wrap")).toBe("anywhere");
  });

  /* A `<th>` is a cell and overflows its column the same way, so the same break is declared on it. Measured in a
   * browser: without this, an unbroken 36-character header in a 60px column draws 267px of content over the
   * column beside it and its own row stays at the pitch. */
  it("breaks one in a header too, which is a cell and overflows its column the same way", async () => {
    expect(await declaredValue(".table__header", "overflow-wrap")).toBe("anywhere");
  });

  it("renders a name at the api's cap in full, in a column narrower than the name", () => {
    const { container } = renderTable({
      columns: [
        { key: "title", header: "Task", width: "88px", cell: (task) => task.title },
        { key: "minutes", header: "Estimate", width: { weight: 1 }, cell: (task) => task.minutes },
      ],
      rows: [{ id: "1", title: NAME_AT_THE_CAP, minutes: 90 }],
    });
    const cell = container.querySelector("tbody td");

    expect(NAME_AT_THE_CAP).toHaveLength(nameCapIn(CONTRACT));
    expect(cell?.textContent).toBe(NAME_AT_THE_CAP);
  });
});

describe("the sheet the policy is drawn by", () => {
  it("fixes the layout on the class the component sets, and on no other selector", async () => {
    const fixed = (await familyDeclarations()).filter((each) => each.includes("table-layout"));

    expect(fixed).toEqual([`${path.join("table", "table.css")} .table--fixed table-layout: fixed`]);
  });

  /* The standing column's reserved width is the one length the policy subtracts, so it is declared against the name
   * the component names and the figure stays in one place. */
  it("reserves the standing column against the name the surplus subtracts", async () => {
    expect(await declaredValue(".table__mark", "width")).toBe("var(--table-mark-w)");
    expect(await declaredValue(".table", "--table-mark-w")).toBe("18px");
  });
});
