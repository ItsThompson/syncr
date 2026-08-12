/* EVERY CONTROL FORWARDS A REF, AND THIS IS WHAT PINS WHICH ELEMENT IT LANDS ON.
 *
 * The component rules require it, and the reason is the product's: a form that cannot focus its first invalid
 * field, or a route that cannot put the caret in a palette's query field, is a keyboard-first product asking
 * for a mouse. A prop that merely compiles does not deliver that, so each case asserts the node the caller
 * actually receives.
 *
 * The set of components is derived from the barrel, so a control cannot be added to the layer and left
 * without a ref: it would have no case here and the last test would name it. */

import { type ReactElement } from "react";
import { render } from "@testing-library/react";
import { Inbox } from "lucide-react";
import { describe, expect, it } from "vitest";

import { componentNamesIn } from "../../../testing/kitExports";
import * as primitives from "../index";

const noop = () => {};

/**
 * A ref the case hands to the component, which records what the component gives back.
 *
 * The callback form rather than a `createRef` object, because one array of cases has to hold fifteen element
 * types: a ref object of the wrong element type is refused, while a callback taking any element is accepted by
 * every one of them, which is the same assignability React's own `Ref<T>` is built on.
 */
type CaptureRef = (node: Element | null) => void;

interface RefCase {
  readonly name: string;
  /** What the ref should land on, as the tag a caller will find on the node. */
  readonly tag: string;
  readonly mount: (ref: CaptureRef) => ReactElement;
}

const REF_CASES: readonly RefCase[] = [
  {
    name: "Button",
    tag: "BUTTON",
    mount: (ref) => (
      <primitives.Button ref={ref} onClick={noop}>
        Approve week
      </primitives.Button>
    ),
  },
  { name: "Icon", tag: "svg", mount: (ref) => <primitives.Icon ref={ref} mark={Inbox} /> },
  {
    name: "Input",
    tag: "INPUT",
    mount: (ref) => <primitives.Input ref={ref} value="Prep" onValueChange={noop} label="Task" />,
  },
  {
    name: "Textarea",
    tag: "TEXTAREA",
    mount: (ref) => (
      <primitives.Textarea ref={ref} value="Note" onValueChange={noop} rows={3} label="Note" />
    ),
  },
  {
    name: "NumberStepper",
    tag: "INPUT",
    mount: (ref) => (
      <primitives.NumberStepper
        ref={ref}
        value={210}
        onValueChange={noop}
        measure="duration"
        label="Estimate"
      />
    ),
  },
  {
    name: "TimeInput",
    tag: "INPUT",
    mount: (ref) => (
      <primitives.TimeInput ref={ref} value="09:15" onValueChange={noop} label="Start" />
    ),
  },
  {
    name: "TimeRangeInput",
    tag: "INPUT",
    mount: (ref) => (
      <primitives.TimeRangeInput
        ref={ref}
        value={{ start: "09:15", end: "10:00" }}
        onValueChange={noop}
        label="Moved to"
      />
    ),
  },
  {
    name: "Select",
    tag: "BUTTON",
    mount: (ref) => (
      <primitives.Select
        ref={ref}
        value="career"
        onValueChange={noop}
        options={[{ value: "career", label: "Career" }]}
        label="Area"
      />
    ),
  },
  {
    name: "DatePicker",
    tag: "INPUT",
    mount: (ref) => (
      <primitives.DatePicker
        ref={ref}
        value="2025-02-19"
        onValueChange={noop}
        today="2025-02-11"
        label="Deadline"
      />
    ),
  },
  {
    name: "Calendar",
    tag: "DIV",
    mount: (ref) => (
      <primitives.Calendar
        ref={ref}
        month={{ year: 2025, month: 2 }}
        onMonthChange={noop}
        selected="2025-02-19"
        onSelect={noop}
        today="2025-02-11"
        label="Deadline"
      />
    ),
  },
  {
    name: "Checkbox",
    tag: "BUTTON",
    mount: (ref) => (
      <primitives.Checkbox ref={ref} state="checked" onStateChange={noop}>
        Splittable
      </primitives.Checkbox>
    ),
  },
  {
    name: "Radio",
    tag: "DIV",
    mount: (ref) => (
      <primitives.Radio
        ref={ref}
        value="forgive"
        onValueChange={noop}
        options={[{ value: "forgive", label: "forgive" }]}
        label="Miss policy"
      />
    ),
  },
  {
    name: "Tabs",
    tag: "DIV",
    mount: (ref) => (
      <primitives.Tabs
        ref={ref}
        value="days"
        onValueChange={noop}
        tabs={[{ value: "days", label: "Day types", content: <p>Four</p> }]}
        label="Sections"
      />
    ),
  },
  {
    name: "Dialog",
    tag: "DIV",
    mount: (ref) => (
      <primitives.Dialog ref={ref} isOpen onOpenChange={noop} title="Approve week">
        <p>91 blocks</p>
      </primitives.Dialog>
    ),
  },
  {
    name: "Command",
    tag: "INPUT",
    mount: (ref) => (
      <primitives.Command
        ref={ref}
        actions={[{ id: "approve", label: "Approve week" }]}
        onSelect={noop}
        label="Command palette"
        emptyLabel="No command matches"
      />
    ),
  },
];

describe("every control in the layer", () => {
  it.each(REF_CASES.map((entry) => [entry.name, entry] as const))(
    "hands %s's ref the element a caller reaches for",
    (_name, entry) => {
      const received: Element[] = [];

      render(
        entry.mount((node) => {
          if (node !== null) received.push(node);
        }),
      );

      expect(received.length).toBeGreaterThan(0);
      expect(received.at(-1)?.tagName).toBe(entry.tag);
    },
  );

  it("leaves no component without a case, because the set comes from the barrel", () => {
    expect(REF_CASES.map((entry) => entry.name).toSorted()).toEqual(componentNamesIn(primitives));
  });
});

describe("asChild", () => {
  /* The recorded decision, asserted where it can be: the one component whose children are the caller's
   * renders the caller's element, which is what makes a navigating button a real link. Every other component
   * composes elements of its own, and `index.ts` records why the prop stays unexposed there. */
  it("renders the caller's own element on the one component that takes one", () => {
    const { container } = render(
      <primitives.Button asChild>
        <a href="/week">Week</a>
      </primitives.Button>,
    );

    const link = container.querySelector("a");
    expect(link).toHaveAttribute("href", "/week");
    expect([...(link?.classList ?? [])]).toContain("button");
  });
});
