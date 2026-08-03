/* A month grid. The date picker's inner surface, and its own component because it is a grid with a keyboard.
 *
 * TODAY IS `aria-current="date"`, WHICH IS A DEPARTURE FROM THE SHEET AND DELIBERATE.
 * `docs/design/components.html` marks it with `data-today`, and the closed state vocabulary is closed: an
 * attribute with no `@custom-variant` is refused by the markup scan, and minting a variant for a state ARIA
 * already models would put one idea in two forms. `aria-current="date"` is what the accessibility model has
 * for exactly this, so the styling hook and the announced state are one attribute.
 *
 * TODAY ARRIVES AS A PROP. A kit component never reaches for a global, and a clock is the most tempting one
 * there is. It is also genuinely the caller's: today depends on the reader's home zone or their travel
 * override, which the domain layer knows and a control cannot.
 *
 * THE CELL IS THE CONTROL, not a button inside it. That is the grid pattern the accessibility guidelines
 * describe for a date picker: one tab stop for the whole month, the arrow keys moving within it, and
 * `aria-selected` on the cell, which is the role that supports it. A button in every cell would put 35 stops
 * in the tab order and would need `aria-pressed`, which announces a toggle rather than a choice. */

import { useEffect, useRef, useState, type KeyboardEvent, type Ref } from "react";

import "./Calendar.css";
import "./glyphs.css";
import {
  WEEKDAY_INITIALS,
  WEEKDAY_NAMES,
  dayLabel,
  monthGrid,
  monthLabel,
  parseIsoDate,
  shiftDate,
  shiftMonth,
  type CalendarMonth,
} from "./month";
import { Button } from "./Button";

const KEY_OFFSETS: Readonly<Record<string, number>> = {
  ArrowLeft: -1,
  ArrowRight: 1,
  ArrowUp: -7,
  ArrowDown: 7,
};

const ACTIVATION_KEYS = new Set([" ", "Enter"]);

export interface CalendarProps {
  /** The month on show. */
  readonly month: CalendarMonth;
  readonly onMonthChange: (next: CalendarMonth) => void;
  /** `YYYY-MM-DD`, or null when nothing is chosen yet. */
  readonly selected: string | null;
  readonly onSelect: (iso: string) => void;
  /** `YYYY-MM-DD` in the reader's own zone, which the caller knows and a control does not. */
  readonly today: string;
  /** Names the grid, which is what a screen reader announces on entering it. */
  readonly label: string;
  /** The calendar, which is the element a popover or a panel positions. */
  readonly ref?: Ref<HTMLDivElement> | undefined;
}

export function Calendar({
  month,
  onMonthChange,
  selected,
  onSelect,
  today,
  label,
  ref,
}: CalendarProps) {
  /* THE CURSOR IS WHERE THE READER LAST WAS, whether they arrived by an arrow key or by a click, and null
   * until they arrive at all. It is one piece of state rather than a position plus a flag: the flag would say
   * "a key has been pressed at some point", which is not a question this component ever needs to ask, and
   * focus would follow every later render.
   *
   * A click sets it too, because the cursor is what the month's one tab stop follows. Setting it on the arrow
   * keys alone left the stop on the last key-moved day, so tabbing out and shift-tabbing back in re-entered
   * the grid on a day the reader had not picked. */
  const [cursor, setCursor] = useState<string | null>(null);
  const cellsByDay = useRef(new Map<string, HTMLTableCellElement>());

  /* Focus moves once per cursor change. Focusing from a ref callback instead would fire on every render,
   * because a new callback identity detaches and re-attaches all 35 cells, and paging the month and back
   * would take focus off the button the reader had just clicked. */
  useEffect(() => {
    if (cursor === null) return;
    cellsByDay.current.get(cursor)?.focus();
  }, [cursor]);

  const weeks = monthGrid(month);
  const days = weeks.flat();
  const inMonth = (iso: string | null) =>
    iso !== null && days.some((day) => day.iso === iso && !day.isOutsideMonth);
  /* One tab stop for the month: where the cursor is, else the chosen day, else today, else the month's
   * first day. The fallback is the first day IN the month rather than the grid's first cell, which is a
   * leading day of the previous month whenever the month does not start on a Monday. */
  const tabStop =
    [cursor, selected, today].find(inMonth) ?? days.find((day) => !day.isOutsideMonth)?.iso ?? null;

  const moveCursor = (from: string, offset: number) => {
    const next = shiftDate(from, offset);
    if (next === null) return;
    setCursor(next);
    const moved = parseIsoDate(next);
    if (moved !== null && (moved.year !== month.year || moved.month !== month.month)) {
      onMonthChange({ year: moved.year, month: moved.month });
    }
  };

  const choose = (iso: string) => {
    setCursor(iso);
    onSelect(iso);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTableCellElement>, iso: string) => {
    if (ACTIVATION_KEYS.has(event.key)) {
      event.preventDefault();
      choose(iso);
      return;
    }
    const offset = KEY_OFFSETS[event.key];
    if (offset === undefined) return;
    event.preventDefault();
    moveCursor(iso, offset);
  };

  return (
    <div className="calendar" ref={ref}>
      <div className="calendar__header">
        <Button
          rank="quiet"
          size="sm"
          label="Previous month"
          onClick={() => onMonthChange(shiftMonth(month, -1))}
        >
          <span className="glyph glyph--month-previous" aria-hidden="true" />
        </Button>
        <span aria-live="polite">{monthLabel(month)}</span>
        <Button
          rank="quiet"
          size="sm"
          label="Next month"
          onClick={() => onMonthChange(shiftMonth(month, 1))}
        >
          <span className="glyph glyph--month-next" aria-hidden="true" />
        </Button>
      </div>
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-to-interactive-role -- a date grid IS the interactive grid pattern: its cells take the arrow keys and carry aria-selected, which the table role does not support */}
      <table className="calendar__grid" role="grid" aria-label={label}>
        <thead>
          <tr>
            {WEEKDAY_INITIALS.map((initial, index) => (
              <th
                key={WEEKDAY_NAMES[index]}
                scope="col"
                className="calendar__weekday"
                abbr={WEEKDAY_NAMES[index]}
              >
                {initial}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0].iso}>
              {week.map((day) => (
                <td
                  key={day.iso}
                  className={
                    day.isOutsideMonth ? "calendar__day calendar__day--outside" : "calendar__day"
                  }
                  tabIndex={day.iso === tabStop ? 0 : -1}
                  aria-selected={day.iso === selected}
                  aria-current={day.iso === today ? "date" : undefined}
                  aria-label={dayLabel(day.iso)}
                  ref={(node) => {
                    if (node === null) cellsByDay.current.delete(day.iso);
                    else cellsByDay.current.set(day.iso, node);
                  }}
                  onKeyDown={(event) => onKeyDown(event, day.iso)}
                  onClick={() => choose(day.iso)}
                >
                  {day.dayOfMonth}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
