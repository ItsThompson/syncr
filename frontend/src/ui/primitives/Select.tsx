/* A select. Radix's, with the native arrow replaced by a typographic mark.
 *
 * The box stays square because there is no native control to draw one: Radix's trigger is a button, so the
 * platform never gets the chance to put the arrow in a well with its own corner radius. The mark comes
 * from the kit's glyph table, and radius is zero here as everywhere.
 *
 * The keyboard cursor is Radix's `data-highlighted`, which maps to FOCUS and nothing else. Its ring is
 * declared once in `states.css`, so a select row, a palette row and a sidebar row cannot disagree about
 * what the cursor looks like. A palette's CURRENT row is `data-current`, which is a different question.
 *
 * The options are data rather than children, because every consumer in this product has a list to hand:
 * Areas, a sort order, a grain. A caller that needs arbitrary content in a row needs a different control. */

import type { Ref } from "react";
import * as RadixSelect from "@radix-ui/react-select";

import "./control.css";
import "./glyphs.css";
import "./overlay.css";
import "./Select.css";
import "./states.css";

export interface SelectOption {
  readonly value: string;
  readonly label: string;
  readonly isDisabled?: boolean | undefined;
}

export interface SelectProps {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly options: readonly SelectOption[];
  /** Shown while nothing is chosen. A select with no placeholder starts on its first option. */
  readonly placeholder?: string | undefined;
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isInvalid?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** Set where no visible label names the control. A form row supplies a real label instead. */
  readonly label?: string | undefined;
  /** The id of the hint or error text under the control, which the form row owns. */
  readonly describedBy?: string | undefined;
  /** The trigger, which is the focusable half of this control and where a form focusing it lands. */
  readonly ref?: Ref<HTMLButtonElement> | undefined;
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  id,
  name,
  isDisabled,
  isInvalid,
  isRequired,
  label,
  describedBy,
  ref,
}: SelectProps) {
  return (
    <RadixSelect.Root
      value={value}
      onValueChange={onValueChange}
      disabled={isDisabled === true}
      required={isRequired === true}
      /* Radix types its optional props as `?: T`, and under `exactOptionalPropertyTypes` an explicit
         undefined is an error, so an absent name is omitted rather than passed. */
      {...(name === undefined ? {} : { name })}
    >
      <RadixSelect.Trigger
        ref={ref}
        id={id}
        className="control select__trigger"
        aria-invalid={isInvalid === true ? true : undefined}
        aria-label={label}
        aria-describedby={describedBy}
      >
        <RadixSelect.Value placeholder={placeholder} />
        <RadixSelect.Icon asChild>
          <span className="glyph glyph--triangle-down select__arrow" aria-hidden="true" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content position="popper" sideOffset={2} className="overlay select__content">
          <RadixSelect.Viewport>
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                disabled={option.isDisabled === true}
                className="state-row select__item"
              >
                <span className="select__indicator" aria-hidden="true">
                  <RadixSelect.ItemIndicator>
                    <span className="glyph glyph--check" />
                  </RadixSelect.ItemIndicator>
                </span>
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  );
}
