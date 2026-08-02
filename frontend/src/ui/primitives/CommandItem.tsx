/* One command row.
 *
 * `data-highlighted` is the keyboard cursor and it maps to FOCUS and nothing else, which is why a highlighted
 * row does not also take the hover wash: a hovered row and the cursor row have to stay distinguishable.
 * `data-current` is a different state on a different channel, and a palette's current row uses it like any
 * other current row in the product.
 *
 * FOCUS STAYS IN THE QUERY FIELD. The row is an `option` and the field points at it with
 * `aria-activedescendant`, which is what lets a reader keep typing while the cursor moves. That is the ARIA
 * combobox pattern, and it is why the row is a div with a role rather than a button: a focusable row would
 * take focus off the field on every keystroke, and `option` is not a tag that exists outside a `select`. */

export interface CommandItemProps {
  readonly id: string;
  readonly label: string;
  /** A key hint or a qualifier, right-aligned. */
  readonly hint?: string | undefined;
  /** The row the palette was opened from, or the row a deep link named. */
  readonly isCurrent?: boolean | undefined;
  /** The keyboard cursor. Exactly one row in the list carries it. */
  readonly isHighlighted: boolean;
  readonly onSelect: () => void;
  readonly onHighlight: () => void;
}

export function CommandItem({
  id,
  label,
  hint,
  isCurrent,
  isHighlighted,
  onSelect,
  onHighlight,
}: CommandItemProps) {
  return (
    // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus -- the ARIA combobox pattern: focus stays in the field and the keys are handled there
    <div
      id={id}
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- `option` is not a tag outside a select or a datalist, and neither can hold a row with a right-aligned hint
      role="option"
      aria-selected={isHighlighted}
      className="state-row command__row"
      data-highlighted={isHighlighted ? "" : undefined}
      data-current={isCurrent === true ? "" : undefined}
      onPointerMove={onHighlight}
      onClick={onSelect}
    >
      <span>{label}</span>
      {hint === undefined ? null : <span className="command__hint">{hint}</span>}
    </div>
  );
}
