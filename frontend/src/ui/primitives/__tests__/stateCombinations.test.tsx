/* THE COMBINATION MATRIX, which is not optional diligence.
 *
 * The design language records the reason by name: in the inherited language four plausible state systems each
 * looked correct on a single state and produced two pixel-identical rows in a combination matrix while meaning
 * different things. `docs/design/scratch/block-states.html` carries syncr's own matrix for the block. This file
 * carries the kit's, over the two families of the primitives layer that have more than one state at a time:
 *
 *   the row      hover, current and the keyboard cursor, which co-occur constantly in a palette or a select
 *   the field     invalid and disabled, which a form drives together
 *
 * WHAT IS ASSERTED IS THE GROUPING, not merely that each state does something. Every combination is rendered,
 * its effective declarations are resolved from the stylesheet, and combinations that land on the same result are
 * grouped. The grouping then has to equal the documented one, so a state that quietly stops adding anything
 * fails here, and so does a pair that starts colliding.
 *
 * TWO PAIRS ARE DELIBERATELY IDENTICAL AND BOTH ARE THE SAME FACT: hover and a current row spend the same fill,
 * --state-hover, so hovering the current row adds nothing. That is by design rather than a collision to fix. The
 * current row is told apart by its 3px left rule, which hover does not touch, so nothing is lost. */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { kitStylesheet, kitStylesheets } from "../../../testing/kitStylesheets";
import { signatureOf } from "../../../testing/visualState";

interface RowState {
  readonly isHovered: boolean;
  readonly isCurrent: boolean;
  readonly isHighlighted: boolean;
}

function rowStates(): RowState[] {
  const states: RowState[] = [];
  for (const isHovered of [false, true]) {
    for (const isCurrent of [false, true]) {
      for (const isHighlighted of [false, true])
        states.push({ isHovered, isCurrent, isHighlighted });
    }
  }
  return states;
}

function nameOf(state: RowState): string {
  const parts = [
    state.isHovered ? "hover" : null,
    state.isCurrent ? "current" : null,
    state.isHighlighted ? "cursor" : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? "rest" : parts.join("+");
}

function renderRow(state: RowState): Element {
  const { container } = render(
    <div
      className="state-row command__row"
      data-current={state.isCurrent ? "" : undefined}
      data-highlighted={state.isHighlighted ? "" : undefined}
    />,
  );
  const row = container.firstElementChild;
  if (row === null) throw new Error("no row rendered");
  return row;
}

/** Combinations that resolve to the same declarations, grouped and named. */
function groupsOf(signatures: Map<string, string>): string[][] {
  const bySignature = new Map<string, string[]>();
  for (const [name, signature] of signatures) {
    bySignature.set(signature, [...(bySignature.get(signature) ?? []), name]);
  }
  return [...bySignature.values()].filter((group) => group.length > 1);
}

describe("the row's states, in every combination", () => {
  async function signatures(): Promise<Map<string, string>> {
    const css = await kitStylesheets("states.css", "Command.css");
    const found = new Map<string, string>();
    for (const state of rowStates()) {
      const active = state.isHovered ? [":hover"] : [];
      found.set(nameOf(state), signatureOf({ element: renderRow(state), css, active }));
    }
    return found;
  }

  it("renders all eight, so the matrix is a matrix", async () => {
    expect((await signatures()).size).toBe(8);
  });

  it("gives each state alone a result of its own", async () => {
    const found = await signatures();

    expect(found.get("hover")).not.toBe(found.get("rest"));
    expect(found.get("current")).not.toBe(found.get("rest"));
    expect(found.get("cursor")).not.toBe(found.get("rest"));
    expect(found.get("hover")).not.toBe(found.get("current"));
    expect(found.get("hover")).not.toBe(found.get("cursor"));
    expect(found.get("current")).not.toBe(found.get("cursor"));
  });

  it("collides in exactly the two documented places, both of them hover on a current row", async () => {
    const groups = groupsOf(await signatures()).map((group) => group.toSorted().join(" == "));

    expect(groups.toSorted()).toEqual([
      "current == hover+current",
      "current+cursor == hover+current+cursor",
    ]);
  });

  it("keeps the cursor's ring in every combination, so the keyboard is never invisible", async () => {
    const withCursor = [...(await signatures()).entries()].filter(([name]) =>
      name.includes("cursor"),
    );

    expect(withCursor).toHaveLength(4);
    expect(withCursor.filter(([, signature]) => signature.includes("outline:"))).toHaveLength(4);
  });

  it("keeps the current row's left rule in every combination, including under the cursor", async () => {
    const rule = "border-left-color: var(--state-selected-color)";
    const withCurrent = [...(await signatures()).entries()].filter(([name]) =>
      name.includes("current"),
    );

    expect(withCurrent).toHaveLength(4);
    expect(withCurrent.filter(([, signature]) => signature.includes(rule))).toHaveLength(4);
  });
});

interface FieldState {
  readonly isInvalid: boolean;
  readonly isDisabled: boolean;
}

function renderField(state: FieldState): Element {
  const { container } = render(
    <input
      type="text"
      className="control"
      aria-invalid={state.isInvalid ? true : undefined}
      disabled={state.isDisabled}
    />,
  );
  const field = container.firstElementChild;
  if (field === null) throw new Error("no field rendered");
  return field;
}

describe("the field's states, in every combination", () => {
  async function signatures(): Promise<Map<string, string>> {
    const css = await kitStylesheet("control.css");
    const found = new Map<string, string>();
    for (const isInvalid of [false, true]) {
      for (const isDisabled of [false, true]) {
        const name = [isInvalid ? "invalid" : null, isDisabled ? "disabled" : null]
          .filter((part) => part !== null)
          .join("+");
        found.set(
          name === "" ? "rest" : name,
          signatureOf({ element: renderField({ isInvalid, isDisabled }), css }),
        );
      }
    }
    return found;
  }

  it("renders all four", async () => {
    expect((await signatures()).size).toBe(4);
  });

  it("gives every combination a result of its own, with no collision to document", async () => {
    expect(groupsOf(await signatures())).toEqual([]);
  });

  /* A disabled field is dashed and muted; an invalid one keeps its fill and takes a 3px oxide left rule. A
   * disabled AND invalid field therefore still says both things, which is what a form re-validating a disabled
   * row needs. */
  it("keeps the invalid rule on a disabled field, so a form does not lose the error", async () => {
    const found = await signatures();

    expect(found.get("invalid+disabled")).toContain(
      "border-left-width: var(--state-conflict-border)",
    );
    expect(found.get("invalid+disabled")).toContain("border-style: dashed");
  });

  it("leaves a resting field with neither, so no state is on by default", async () => {
    const rest = await signatures().then((found) => found.get("rest") ?? "");

    expect(rest).not.toContain("--state-conflict-border");
    expect(rest).not.toContain("dashed");
  });
});
