/* WHAT COUNTS AS AN EXPORTED COMPONENT, which is what the layer's coverage checks derive their sets from.
 *
 * `mounting.test.tsx` and `refs.test.tsx` both assert their own coverage against this, so a component the
 * rule fails to recognise drops out of both at once: it would be mounted nowhere, handed no ref, and no test
 * would say so. That is the hole the barrel derivation was built to close, so the rule itself gets cases.
 *
 * The wrapper case is the one that matters. Nothing in the layer is wrapped in `memo` or `forwardRef` today,
 * and both return an object rather than a function. */

import { memo } from "react";
import { describe, expect, it } from "vitest";

import { componentNamesIn } from "./kitExports";

function Button() {
  return null;
}

const MemoButton = memo(Button);

describe("the components a barrel exports", () => {
  it("holds a plain component function", () => {
    expect(componentNamesIn({ Button })).toEqual(["Button"]);
  });

  it("holds a component React wrapped, which is an object rather than a function", () => {
    expect(componentNamesIn({ MemoButton })).toEqual(["MemoButton"]);
  });

  it("leaves out a lowercase function, which is the layer's date and clock arithmetic", () => {
    expect(componentNamesIn({ dayLabel: () => "Wednesday", snapClock: () => "09:15" })).toEqual([]);
  });

  it("leaves out a constant, whatever its name looks like", () => {
    expect(componentNamesIn({ WEEKDAY_NAMES: ["Monday"], SNAP_MINUTES: 15 })).toEqual([]);
  });

  it("leaves out an object that is not React's, so a config export is not a component", () => {
    expect(componentNamesIn({ Settings: { rank: "primary" } })).toEqual([]);
  });

  it("reads them in a stable order, so a failure names the difference and not the ordering", () => {
    expect(componentNamesIn({ Tabs: Button, Accordion: Button })).toEqual(["Accordion", "Tabs"]);
  });
});
