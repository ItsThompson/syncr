/* EVERY PRIMITIVE, MOUNTED ONCE, WITH THE CONSOLE WATCHED.
 *
 * The per-component files assert behaviour. This one asserts that mounting the layer produces no complaint from
 * React or from the DOM: a duplicate key, an invalid nesting, a controlled field with no handler, an ARIA
 * attribute a role does not support. Those warnings do not fail a test that ignores them, which is how they
 * accumulate, and every one of them is a real defect at runtime.
 *
 * It is also the layer's smoke test: each component has to render with the props its own type demands. The
 * set of components is READ FROM THE BARREL rather than restated below, because a list beside the cases
 * cannot report the component it does not name: comparing one hand-written list against another lets an
 * export nothing mounts pass unnoticed. */

import { render } from "@testing-library/react";
import { Inbox } from "lucide-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { componentNamesIn } from "../../../testing/kitExports";
import * as primitives from "../index";
import {
  Button,
  Calendar,
  Checkbox,
  Command,
  DatePicker,
  Dialog,
  Icon,
  Input,
  NumberStepper,
  Radio,
  Select,
  Tabs,
  Textarea,
  TimeInput,
  TimeRangeInput,
} from "../index";

const noop = () => {};

/* One entry per exported component, so a new primitive has to appear here to pass review. */
const PRIMITIVES: readonly (readonly [string, () => React.ReactElement])[] = [
  ["Button", () => <Button onClick={noop}>Approve week</Button>],
  ["Icon", () => <Icon mark={Inbox} />],
  ["Input", () => <Input value="Prep" onValueChange={noop} label="Task" />],
  ["Textarea", () => <Textarea value="Note" onValueChange={noop} rows={3} label="Note" />],
  [
    "NumberStepper",
    () => <NumberStepper value={210} onValueChange={noop} measure="duration" label="Estimate" />,
  ],
  ["TimeInput", () => <TimeInput value="09:15" onValueChange={noop} label="Start" />],
  [
    "TimeRangeInput",
    () => (
      <TimeRangeInput
        value={{ start: "09:15", end: "10:00" }}
        onValueChange={noop}
        label="Moved to"
      />
    ),
  ],
  [
    "Select",
    () => (
      <Select
        value="career"
        onValueChange={noop}
        options={[{ value: "career", label: "Career" }]}
        label="Area"
      />
    ),
  ],
  [
    "DatePicker",
    () => (
      <DatePicker value="2025-02-19" onValueChange={noop} today="2025-02-11" label="Deadline" />
    ),
  ],
  [
    "Calendar",
    () => (
      <Calendar
        month={{ year: 2025, month: 2 }}
        onMonthChange={noop}
        selected="2025-02-19"
        onSelect={noop}
        today="2025-02-11"
        label="Deadline"
      />
    ),
  ],
  [
    "Checkbox",
    () => (
      <Checkbox state="checked" onStateChange={noop}>
        Splittable
      </Checkbox>
    ),
  ],
  [
    "Radio",
    () => (
      <Radio
        value="forgive"
        onValueChange={noop}
        options={[
          { value: "forgive", label: "forgive" },
          { value: "debt", label: "debt" },
        ]}
        label="Miss policy"
      />
    ),
  ],
  [
    "Tabs",
    () => (
      <Tabs
        value="days"
        onValueChange={noop}
        tabs={[{ value: "days", label: "Day types", count: 4, content: <p>Four</p> }]}
        label="Sections"
      />
    ),
  ],
  [
    "Dialog",
    () => (
      <Dialog isOpen onOpenChange={noop} title="Approve week" footer={<Button>Approve</Button>}>
        <p>91 blocks</p>
      </Dialog>
    ),
  ],
  [
    "Command",
    () => (
      <Command
        actions={[{ id: "approve", label: "Approve week", group: "Plan", hint: "shift a" }]}
        onSelect={noop}
        label="Command palette"
        emptyLabel="No command matches"
      />
    ),
  ],
];

describe("the primitives layer", () => {
  const complaints: string[] = [];

  beforeEach(() => {
    complaints.length = 0;
    vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      complaints.push(`error: ${args.join(" ")}`);
    });
    vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
      complaints.push(`warn: ${args.join(" ")}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each(PRIMITIVES)("mounts %s with nothing to complain about", (_name, mount) => {
    render(mount());

    expect(complaints).toEqual([]);
  });

  it("exports every component the inventory names, and nothing this file has not mounted", () => {
    expect(PRIMITIVES.map(([name]) => name).toSorted()).toEqual(componentNamesIn(primitives));
  });
});
