/* The form row, and the wiring it exists to make impossible to get wrong.
 *
 * A label that points at nothing and a field that is described by nothing both render correctly, which is why
 * the row mints the ids and hands them to the field rather than documenting a convention. These cases assert
 * the accessible relationships rather than the class names, because the relationships are the contract.
 *
 * THE GROUP FORM IS THE SAME ARGUMENT ONE STEP ON. A radio group and an interval cannot be pointed at by a
 * label at all, so the row draws the words in an element of its own and hands the child that element's id.
 * The cases below drive that through the real controls rather than through a stub, because what is being
 * asserted is a name a browser computes from two elements and not a prop the row passed. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { authoredNames, danglingLabels } from "../../testing/accessibleNames";
import { kitStylesheet, layoutDir } from "../../testing/kitStylesheets";
import { Input, Radio, TimeRangeInput } from "../primitives";
import { FormRow, type FormRowField, type FormRowGroupField, type FormRowProps } from "./FormRow";

/* The row's own props, without the child: every case here renders the same single control and varies the
 * words around it. */
type RowWords = Partial<Pick<FormRowProps, "label" | "hint" | "error" | "isRequired">>;

function renderRow(props: RowWords = {}) {
  return render(
    <FormRow label="Estimate" {...props}>
      {(field) => (
        <Input
          id={field.id}
          describedBy={field.describedBy}
          value="45"
          onValueChange={vi.fn<(next: string) => void>()}
        />
      )}
    </FormRow>,
  );
}

describe("the label column", () => {
  it("labels the field the row rendered, through the id the row minted", () => {
    renderRow();

    expect(screen.getByLabelText("Estimate")).toHaveValue("45");
  });

  it("marks a required row, and leaves the announcement to the field", () => {
    renderRow({ isRequired: true });

    expect(screen.getByText("*")).toBeInTheDocument();
  });
});

describe("the message under the field", () => {
  it("describes the field when it is a hint", () => {
    renderRow({ hint: "minutes, stepping by 15" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "minutes, stepping by 15",
    );
  });

  it("describes the field when it is an error", () => {
    renderRow({ error: "an estimate cannot be zero" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "an estimate cannot be zero",
    );
  });

  /* One slot, so becoming invalid changes the words rather than the row's height. */
  it("is the error and not the hint when there is both", () => {
    renderRow({ hint: "minutes, stepping by 15", error: "an estimate cannot be zero" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "an estimate cannot be zero",
    );
    expect(screen.queryByText("minutes, stepping by 15")).toBeNull();
  });

  /* THE TEXT STEP, READ FROM THE STYLESHEET. An error message is words, so it takes --oxide-ink at 4.5:1 and not
   * the marker step, which is sealed to dots, rules and glyphs at 3:1. Nothing in a rendering can see which of the
   * two a rule chose, so the rule is what this reads. */
  it("takes the signal's TEXT step rather than its marker step, which fails 4.5:1", async () => {
    const { container } = renderRow({ error: "an estimate cannot be zero" });
    const css = await kitStylesheet("FormRow.css", layoutDir);
    const message = /\.form-row__message--error\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";

    expect(container.querySelector(".form-row__message--error")).toHaveTextContent(
      "an estimate cannot be zero",
    );
    expect(message).toContain("color: var(--oxide-ink)");
    expect(message).not.toContain("--signal-oxide");
  });

  it("describes the field by nothing when there is no message at all", () => {
    renderRow();

    expect(screen.getByLabelText("Estimate")).not.toHaveAttribute("aria-describedby");
  });

  it("mints ids per row, so two rows on one screen do not both answer to one id", () => {
    const { container } = render(
      <>
        <FormRow label="Estimate" hint="minutes">
          {(field) => <input id={field.id} aria-describedby={field.describedBy} />}
        </FormRow>
        <FormRow label="Minimum chunk" hint="minutes">
          {(field) => <input id={field.id} aria-describedby={field.describedBy} />}
        </FormRow>
      </>,
    );

    const ids = [...container.querySelectorAll("input")].map((field) => field.id);
    expect(new Set(ids).size).toBe(2);
  });
});

const OPTIONS = [
  { value: "concrete", label: "concrete" },
  { value: "slot", label: "slot" },
];

const BOUNDS = { start: "07:00", end: "22:00" };

/* One hint per row, and the cases below give them different words, so a row whose message answered another
 * row's control fails rather than passing on a string that happens to match. */
interface GroupHints {
  readonly kind?: string | undefined;
  readonly bounds?: string | undefined;
}

function renderGroups(hints: GroupHints = {}) {
  return render(
    <>
      <FormRow label="Kind" hint={hints.kind} isGroup>
        {(field) => (
          <Radio
            labelledBy={field.labelledBy}
            describedBy={field.describedBy}
            value="slot"
            onValueChange={vi.fn<(next: string) => void>()}
            options={OPTIONS}
          />
        )}
      </FormRow>
      <FormRow label="Day bounds" hint={hints.bounds} isGroup>
        {(field) => (
          <TimeRangeInput
            labelledBy={field.labelledBy}
            describedBy={field.describedBy}
            value={BOUNDS}
            onValueChange={vi.fn<(next: typeof BOUNDS) => void>()}
          />
        )}
      </FormRow>
    </>,
  );
}

/* Both controls are rendered for real rather than stubbed, because the claim is about a name a browser
 * computes from two elements and not about a prop the row passed down. */
describe("the group form", () => {
  it("names a radio group by the element the row drew, and by no string of its own", () => {
    renderGroups();
    const group = screen.getByRole("radiogroup", { name: "Kind" });

    expect(group).toHaveAttribute("aria-labelledby", screen.getByText("Kind").id);
    expect(group).not.toHaveAttribute("aria-label");
  });

  it("names an interval by the element the row drew, and by no string of its own", () => {
    renderGroups();
    const interval = screen.getByRole("group", { name: "Day bounds" });

    expect(interval).toHaveAttribute("aria-labelledby", screen.getByText("Day bounds").id);
    expect(interval).not.toHaveAttribute("aria-label");
  });

  /* TWO ROWS, TWO QUESTIONS, which is what makes the name a DERIVED one. A row handing out one shared id
   * names both groups by whichever element the document reaches first, and satisfies either case on its own. */
  it("names each group by its own row's words rather than by another row's", () => {
    const { container } = renderGroups();

    expect(authoredNames(container, "Kind")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);
    expect(authoredNames(container, "Day bounds")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);
  });

  /* The row cannot point a label at a radio group's tab stop or at a fieldset, and a label aimed at either
   * renders correctly while naming nothing, per `ui/primitives/naming.ts`. So the group form draws a span, and
   * the labels left in the render are the options' own. */
  it("leaves no label pointing at nothing, in either form", () => {
    const groups = renderGroups();
    expect(danglingLabels(groups.container)).toEqual([]);

    const single = renderRow({ hint: "minutes" });
    expect(danglingLabels(single.container)).toEqual([]);
  });

  /* The row hands its child a `describedBy` whichever control the child is, so BOTH supported controls take
   * it: a group form whose message slot reached one of the two would render a message nothing references, and
   * the type cannot see an ignored field. Each row's words differ, so a control describing itself by another
   * row's message fails here. */
  it("describes each group by its own row's message slot", () => {
    renderGroups({
      kind: "A concrete entry keeps its hour; a slot leaves the hour to the solver.",
      bounds: "Wall time, in whichever zone is active on the day.",
    });

    expect(screen.getByRole("radiogroup", { name: "Kind" })).toHaveAccessibleDescription(
      "A concrete entry keeps its hour; a slot leaves the hour to the solver.",
    );
    expect(screen.getByLabelText("from")).toHaveAccessibleDescription(
      "Wall time, in whichever zone is active on the day.",
    );
  });

  /* A required row draws the marker as a child of the label element, so the words and the marker are two nodes
   * in one span. The census reads the span's OWN text, which is why the row is still one authoring rather than
   * none, and the group's name carries the marker because the marker sits inside the element it points at. */
  it("authors a required group row's words once, marker and all", () => {
    const { container } = render(
      <FormRow label="Day bounds" isRequired isGroup>
        {(field) => (
          <TimeRangeInput
            labelledBy={field.labelledBy}
            value={BOUNDS}
            onValueChange={vi.fn<(next: typeof BOUNDS) => void>()}
          />
        )}
      </FormRow>,
    );

    expect(authoredNames(container, "Day bounds")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);
    expect(screen.getByRole("group", { name: "Day bounds*" })).toBeInTheDocument();
  });
});

/* THE LABEL ELEMENT AND THE CHILD'S IDS ARE ONE DECISION, and this is where that is enforced rather than
 * reviewed: a row whose label points at a field while its child is named by an element, or the reverse, is a
 * row whose label names nothing. Both directions are refused by the typecheck, and `tsc --noEmit` runs over
 * `src`, so a directive that stops erroring fails it. */
describe("the compiler", () => {
  it("refuses a group row a child that takes a field's id", () => {
    const row = (
      // @ts-expect-error a group is named by the element the row drew and no label points at it
      <FormRow label="Kind" isGroup>
        {(field: FormRowField) => <input id={field.id} />}
      </FormRow>
    );

    expect(render(row).container.querySelector(".form-row")).not.toBeNull();
  });

  it("refuses a single-control row a child that names itself by an element", () => {
    const row = (
      // @ts-expect-error the row points its own label at this child, so there is no element id to hand out
      <FormRow label="Estimate">
        {(field: FormRowGroupField) => <input aria-labelledby={field.labelledBy} />}
      </FormRow>
    );

    expect(render(row).container.querySelector(".form-row")).not.toBeNull();
  });
});
