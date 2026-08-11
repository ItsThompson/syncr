/* A radio group. One radio on its own means nothing, so the primitive is the group.
 *
 * The dot is one of the four legal circles, with the status dot, the Area chip and the avatar, and the
 * allowlist is closed at those four. It is an element rather than a glyph because a filled circle at 6px is
 * geometry: a glyph would be a character whose weight and baseline vary by font.
 *
 * Radix owns the roving tab order, so the group takes one tab stop and the arrow keys move within it, which
 * is what a keyboard-first product needs from a set of exclusive choices.
 *
 * THE GROUP CANNOT BE POINTED AT BY A LABEL, because its tab stop is a descendant Radix owns, so it is named
 * either by a string of its own or by an element a screen has already drawn the question in. See `naming.ts`. */

import { useId, type Ref } from "react";
import * as RadixRadioGroup from "@radix-ui/react-radio-group";

import type { GroupNaming } from "./naming";
import "./toggle.css";

export interface RadioOption {
  readonly value: string;
  readonly label: string;
  readonly isDisabled?: boolean | undefined;
}

export type RadioProps = GroupNaming & {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly options: readonly RadioOption[];
  readonly name?: string | undefined;
  readonly isDisabled?: boolean | undefined;
  readonly isRequired?: boolean | undefined;
  /** The id of the hint or error text under the group, which the form row owns. */
  readonly describedBy?: string | undefined;
  /**
   * The group, because one radio on its own means nothing and the group is what a form points at.
   *
   * Radix owns the roving tab order, so the group's one tab stop is a descendant rather than the group
   * itself: a caller that means to focus the choice reads `[role="radio"][tabindex="0"]` off this node.
   */
  readonly ref?: Ref<HTMLDivElement> | undefined;
};

export function Radio({
  value,
  onValueChange,
  options,
  label,
  labelledBy,
  describedBy,
  name,
  isDisabled,
  isRequired,
  ref,
}: RadioProps) {
  const groupId = useId();

  return (
    <RadixRadioGroup.Root
      ref={ref}
      className="flex flex-col gap-1"
      value={value}
      onValueChange={onValueChange}
      disabled={isDisabled}
      required={isRequired}
      name={name}
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
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
