/* A radio group. One radio on its own means nothing, so the primitive is the group.
 *
 * The dot is one of the four legal circles, with the status dot, the Area chip and the avatar, and the
 * allowlist is closed at those four. It is an element rather than a glyph because a filled circle at 6px is
 * geometry: a glyph would be a character whose weight and baseline vary by font.
 *
 * Radix owns the roving tab order, so the group takes one tab stop and the arrow keys move within it, which
 * is what a keyboard-first product needs from a set of exclusive choices. */

import { useId } from "react";
import * as RadixRadioGroup from "@radix-ui/react-radio-group";

import "./toggle.css";

export interface RadioOption {
  readonly value: string;
  readonly label: string;
  readonly isDisabled?: boolean | undefined;
}

export interface RadioProps {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly options: readonly RadioOption[];
  /** Names the group, which is what a screen reader announces before the chosen option. */
  readonly label: string;
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
}

export function Radio({
  value,
  onValueChange,
  options,
  label,
  name,
  isDisabled,
  isRequired,
}: RadioProps) {
  const groupId = useId();

  return (
    <RadixRadioGroup.Root
      className="flex flex-col gap-1"
      value={value}
      onValueChange={onValueChange}
      disabled={isDisabled}
      required={isRequired}
      name={name}
      aria-label={label}
    >
      {options.map((option) => {
        const optionId = `${groupId}-${option.value}`;
        return (
          <span className="toggle" key={option.value}>
            <RadixRadioGroup.Item
              id={optionId}
              value={option.value}
              disabled={option.isDisabled}
              className="toggle__box toggle__box--circle"
            >
              <RadixRadioGroup.Indicator asChild>
                <span className="toggle__dot" />
              </RadixRadioGroup.Indicator>
            </RadixRadioGroup.Item>
            <label htmlFor={optionId} className="toggle__label text-sm">
              {option.label}
            </label>
          </span>
        );
      })}
    </RadixRadioGroup.Root>
  );
}
