/* The primitives layer: every Radix-backed control the seven screens demand, and nothing more.
 *
 * The layer may import NOTHING above it. `scripts/check-imports` resolves every import here against the
 * filesystem and refuses one that lands in `ui/layout`, `ui/domain`, `api/`, `contract/`, `routes/` or
 * `app/`, and oxlint refuses the same by specifier. A control that needs to name a `Problem` is misfiled,
 * not under-permitted.
 *
 * WHAT IS DELIBERATELY ABSENT, and why. These are not omissions and a later ticket should not add one
 * without reopening the decision in `14-ui-kit.md`:
 *
 *   Tooltip      No value in this product is reachable only by hovering. A readout row does the work, and
 *                a tooltip would put a fact behind a pointer where a keyboard cannot reach it.
 *   Toast        A notice's position is determined by its volume: inline, panel or banner. A floating
 *                transient would be a fourth volume that contradicts the three the severity model defines.
 *   Skeleton     Motion is zero, without exception. Progress that must be shown is a count that changes,
 *   Spinner      which is a discrete redraw. `--radius` is 0 and the circle allowlist has no spinner on it,
 *   ProgressBar  so the usual spinner cannot be drawn in this language at all.
 *   Popover      Nothing in the seven screens needs one as a component. The detail panel is a column, not a
 *                popover. `@radix-ui/react-popover` is used INSIDE `DatePicker` to anchor its month grid,
 *                which is a surface the design language already sanctions; what is absent is a general
 *                popover a screen could reach for to hide a value behind a click.
 *   LineChart    The Area seal permits ink on a wedge or a bar fill, not on a line, and twelve cobalt lines
 *                separated only by dash pattern is unreadable.
 *
 * `Icon` is here rather than in the inventory because the icon policy needs a home: three sizes read from
 * --icon-sm, --icon and --icon-lg, with the stroke, caps and joins read from tokens. Ticket 3 deferred the
 * sidebar's icons to this ticket for exactly that reason, since half-building them would hard-code the
 * values the tokens already state. */

export { Accordion, type AccordionProps, type AccordionSection } from "./Accordion";
export { Button, type ButtonProps, type ButtonRank } from "./Button";
export { Calendar, type CalendarProps } from "./Calendar";
export { Checkbox, type CheckboxProps, type CheckboxState } from "./Checkbox";
export { Command, type CommandAction, type CommandProps } from "./Command";
export { CommandItem, type CommandItemProps } from "./CommandItem";
export { DatePicker, type DatePickerProps } from "./DatePicker";
export { Dialog, type DialogProps } from "./Dialog";
export { Icon, type IconProps } from "./Icon";
export { Input, type InputProps } from "./Input";
export { NumberStepper, type NumberStepperMeasure, type NumberStepperProps } from "./NumberStepper";
export { Radio, type RadioOption, type RadioProps } from "./Radio";
export { Select, type SelectOption, type SelectProps } from "./Select";
export { Tabs, type Tab, type TabsProps } from "./Tabs";
export { Textarea, type TextareaProps } from "./Textarea";
export { TimeInput, type TimeInputProps } from "./TimeInput";
export { TimeRangeInput, type TimeRange, type TimeRangeInputProps } from "./TimeRangeInput";

export {
  RECORDED_STEP_MINUTES,
  SNAP_MINUTES,
  formatClock,
  parseClock,
  snapClock,
  snapMinutes,
} from "./quarterHour";
export {
  WEEKDAY_INITIALS,
  WEEKDAY_NAMES,
  formatIsoDate,
  monthGrid,
  monthLabel,
  parseIsoDate,
  shiftDate,
  shiftMonth,
  type CalendarDay,
  type CalendarMonth,
} from "./month";
