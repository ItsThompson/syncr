/* The primitives layer: every Radix-backed control the seven screens demand, and nothing more.
 *
 * The layer may import NOTHING above it. `scripts/check-imports` resolves every import here against the
 * filesystem and refuses one that lands in `ui/layout`, `ui/domain`, `api/`, `contract/`, `routes/` or
 * `app/`, and oxlint refuses the same by specifier. A control that needs to name a `Problem` is misfiled,
 * not under-permitted.
 *
 * IMPORTING ONE CONTROL LOADS EVERY CONTROL'S STYLESHEET, and that is accepted rather than overlooked. Each
 * control imports its own sheet for the side effect and this barrel re-exports all of them, so a screen that
 * takes `Button` from here is served the whole layer's CSS. The screens render this layer, and a control none
 * of them has adopted still ships its sheet, so what the side effect costs is measured rather than assumed:
 * `npm run lint:bundle` builds one import through this barrel and one from the control's own module, and
 * prints the difference. The alternative is a barrel with no side effects, which costs a second import
 * convention across the kit -- a control from one path, its stylesheet from another -- for
 * `scripts/check-imports` and oxlint to police, and it breaks the property both of them hold: that
 * `ui/primitives` is one thing.
 *
 * WHAT IS DELIBERATELY ABSENT, and why. These are not omissions and a later ticket should not add one
 * without reopening the decision each entry records:
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
 * --icon-sm, --icon and --icon-lg, with the stroke, caps and joins read from tokens. Drawing an icon anywhere
 * else hard-codes the values the tokens already state.
 *
 * REFS AND `asChild`, WHICH ARE NOT THE SAME DECISION.
 *
 * Every control here forwards a ref, to the element a caller would reach for: the focusable half of a field
 * family control, the query field of the command list, the panel of the dialog, the group of the radio set.
 * That is what lets a form focus its first invalid field and a route put the caret where the reader is about
 * to type, in a product whose primary input is a keyboard. Each prop names the element it lands on, and
 * `__tests__/refs.test.tsx` renders every export and asserts the node it receives.
 *
 * `asChild` is exposed on `Button` alone, and the reason is structural rather than a matter of demand.
 * `Button` renders ONE element and its children are the caller's, so substituting the element changes
 * nothing the kit decided: an anchor with an href keeps middle-click and cmd-click, which is what makes the
 * rule that anything navigating is a real link satisfiable at all. Every other component here either
 * composes several elements of its own (the dialog's header, body and footer; the checkbox's box and its
 * label; the select's trigger and its list) or takes its rows as DATA rather than as children. In both
 * shapes there is no single child element to substitute: the prop would have to arrive as a render prop per
 * part, and it would hand a caller one piece of a structure this kit designed. Radix supports `asChild` on
 * several of those roots, and it stays unexposed here until a screen states which part it needs and why.
 *
 * A navigating tab strip is the case that looks like it wants one and does not: a Radix tab trigger switches
 * a panel in place, and a strip of links that changes the route is a `nav`, which the layout layer owns.
 *
 * `CommandItem` is deliberately not exported. A palette row is composed from the actions `Command` is given,
 * because a caller assembling rows would be composing a row this kit has not designed. */

export { Button, type ButtonProps, type ButtonRank } from "./Button";
export { Calendar, type CalendarProps } from "./Calendar";
export { Checkbox, type CheckboxProps, type CheckboxState } from "./Checkbox";
export { Command, type CommandAction, type CommandProps } from "./Command";
export { DatePicker, type DatePickerProps } from "./DatePicker";
export { Dialog, type DialogProps } from "./Dialog";
export { Icon, type IconProps } from "./Icon";
export { Input, type InputProps } from "./Input";
export type { GroupNaming } from "./naming";
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
  dayLabel,
  formatIsoDate,
  monthGrid,
  monthLabel,
  parseIsoDate,
  shiftDate,
  shiftMonth,
  type CalendarDay,
  type CalendarMonth,
} from "./month";
