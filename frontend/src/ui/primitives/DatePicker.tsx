/* A date picker: an ISO date field, and a month grid in a popover.
 *
 * THE FIELD IS TYPEABLE AND IT IS THE PRIMARY WAY IN. This is a keyboard-first product, and `2025-02-19` is
 * four keystrokes fewer than nine arrow presses. The grid is for the case a reader is choosing rather than
 * stating: a deadline "the Friday after next" is a question about a calendar.
 *
 * The trigger is a separate button rather than the field itself, so clicking into the text to fix one digit
 * does not open and close a popover under the cursor.
 *
 * `today` is the caller's, because today depends on the reader's home zone or their travel override. A
 * control that read a clock would also be a control no test could pin to a date. */

import { useState, type Ref } from "react";
import * as RadixPopover from "@radix-ui/react-popover";

import "./control.css";
import "./DatePicker.css";
import "./glyphs.css";
import "./overlay.css";
import { Calendar } from "./Calendar";
import { parseIsoDate, type CalendarMonth } from "./month";

function monthOf(iso: string, fallback: string): CalendarMonth {
  const parsed = parseIsoDate(iso) ?? parseIsoDate(fallback);
  if (parsed === null) return { year: 1970, month: 1 };
  return { year: parsed.year, month: parsed.month };
}

export interface DatePickerProps {
  /** `YYYY-MM-DD`, or an empty string while nothing is chosen. */
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  /** `YYYY-MM-DD` in the reader's own zone. */
  readonly today: string;
  /** Names the control. A form row supplies a visible label and passes its text here too. */
  readonly label: string;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** The id of the hint or error text under the field, which the form row owns. */
  readonly describedBy?: string | undefined;
  /** The date field, which is the typeable primary way in and where a form focusing this lands. */
  readonly ref?: Ref<HTMLInputElement> | undefined;
}

export function DatePicker({
  value,
  onValueChange,
  today,
  label,
  id,
  name,
  isDisabled,
  isInvalid,
  isRequired,
  describedBy,
  ref,
}: DatePickerProps) {
  const [isOpen, setOpen] = useState(false);
  const [month, setMonth] = useState<CalendarMonth>(() => monthOf(value, today));

  const choose = (iso: string) => {
    onValueChange(iso);
    setOpen(false);
  };

  return (
    <RadixPopover.Root open={isOpen} onOpenChange={setOpen}>
      <RadixPopover.Anchor asChild>
        <span className="date-picker">
          <input
            ref={ref}
            type="text"
            inputMode="numeric"
            className="control control--figure date-picker__field"
            id={id}
            name={name}
            value={value}
            placeholder="YYYY-MM-DD"
            disabled={isDisabled}
            required={isRequired}
            aria-invalid={isInvalid === true ? true : undefined}
            aria-label={label}
            aria-describedby={describedBy}
            onChange={(event) => onValueChange(event.target.value)}
          />
          <RadixPopover.Trigger
            className="date-picker__trigger"
            disabled={isDisabled}
            aria-label={`${label}, choose from a calendar`}
          >
            <span className="glyph glyph--triangle-down" aria-hidden="true" />
          </RadixPopover.Trigger>
        </span>
      </RadixPopover.Anchor>
      <RadixPopover.Portal>
        <RadixPopover.Content
          className="overlay date-picker__panel"
          align="start"
          sideOffset={2}
          aria-label={label}
        >
          <Calendar
            month={month}
            onMonthChange={setMonth}
            selected={value === "" ? null : value}
            onSelect={choose}
            today={today}
            label={label}
          />
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
