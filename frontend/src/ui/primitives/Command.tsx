/* A command list: a query field, a filtered list of actions, and a keyboard cursor.
 *
 * There is no Radix primitive for this, so the one thing that matters is that it behaves like the Radix
 * controls beside it: the cursor is `data-highlighted`, which maps to focus and nothing else, and the row a
 * palette was opened from is `data-current` like any other current row. Both are declared in `states.css`
 * once for the whole kit.
 *
 * It is a combobox rather than a list with a moving focus. Focus stays in the query field so a reader can
 * keep typing while the cursor moves, and `aria-activedescendant` is what tells a screen reader which row
 * the cursor is on. Moving real focus to each row would interrupt typing on every keystroke.
 *
 * THE CURSOR IS DERIVED RATHER THAN STORED. A stored index goes stale the moment the query narrows the list
 * under it, and the usual repair is an effect that resets it after the render that was already wrong. The
 * component keeps the highlighted ACTION ID and falls back to the first result whenever that id is not in
 * the current results, so there is no state to synchronise and no effect at all. */

import { useState, type KeyboardEvent } from "react";

import "./Command.css";
import "./states.css";
import { CommandItem } from "./CommandItem";

export interface CommandAction {
  readonly id: string;
  readonly label: string;
  /** Rows are grouped in the order the groups first appear. Absent means an ungrouped row. */
  readonly group?: string | undefined;
  /** A key hint or a qualifier, right-aligned on the row. */
  readonly hint?: string | undefined;
  /** The row the palette was opened from. Zero or one action carries it. */
  readonly isCurrent?: boolean | undefined;
}

export interface CommandProps {
  readonly actions: readonly CommandAction[];
  readonly onSelect: (id: string) => void;
  /** Names the combobox, which is what a screen reader announces before the query field. */
  readonly label: string;
  readonly placeholder?: string | undefined;
  /** Shown in place of the list when the query matches nothing. */
  readonly emptyLabel: string;
}

/* The field points at the list with `aria-controls`, so both need the same id and only one control of this
 * kind is on screen at a time: a palette is a modal surface. */
const LIST_ID = "command-list";

function matching(actions: readonly CommandAction[], query: string): readonly CommandAction[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return actions;
  return actions.filter((action) => action.label.toLowerCase().includes(needle));
}

/** The groups in the order they first appear, each with its rows. */
function grouped(actions: readonly CommandAction[]): readonly [string, CommandAction[]][] {
  const groups = new Map<string, CommandAction[]>();
  for (const action of actions) {
    const key = action.group ?? "";
    const rows = groups.get(key);
    if (rows === undefined) groups.set(key, [action]);
    else rows.push(action);
  }
  return [...groups.entries()];
}

export function Command({ actions, onSelect, label, placeholder, emptyLabel }: CommandProps) {
  const [query, setQuery] = useState("");
  const [requestedId, setRequestedId] = useState<string | null>(null);

  const results = matching(actions, query);
  const hasResults = results.length > 0;
  const highlighted =
    results.find((action) => action.id === requestedId)?.id ?? results[0]?.id ?? null;

  const move = (offset: number) => {
    if (!hasResults) return;
    const current = results.findIndex((action) => action.id === highlighted);
    const next = (current + offset + results.length) % results.length;
    setRequestedId(results[next].id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
      return;
    }
    if (event.key === "Enter" && highlighted !== null) {
      event.preventDefault();
      onSelect(highlighted);
    }
  };

  return (
    <div className="command">
      <input
        type="text"
        role="combobox"
        className="command__query"
        value={query}
        placeholder={placeholder}
        aria-label={label}
        aria-expanded={hasResults}
        aria-controls={LIST_ID}
        aria-activedescendant={highlighted ?? undefined}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {hasResults ? (
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- a select cannot hold a group heading and a right-aligned hint, and a datalist cannot be styled: this is the ARIA combobox pattern
        <div id={LIST_ID} role="listbox" aria-label={label} className="command__list">
          {grouped(results).map(([group, rows]) => (
            // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- `group` inside a listbox heads a run of options; `optgroup` exists only inside a select
            <div key={group === "" ? "ungrouped" : group} role="group" aria-label={group}>
              {group === "" ? null : <p className="command__group">{group}</p>}
              {rows.map((action) => (
                <CommandItem
                  key={action.id}
                  id={action.id}
                  label={action.label}
                  hint={action.hint}
                  isCurrent={action.isCurrent}
                  isHighlighted={action.id === highlighted}
                  onSelect={() => onSelect(action.id)}
                  onHighlight={() => setRequestedId(action.id)}
                />
              ))}
            </div>
          ))}
        </div>
      ) : (
        <p className="command__empty">{emptyLabel}</p>
      )}
    </div>
  );
}
