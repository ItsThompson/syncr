/* Which Areas a recovery window forbids: a box per Area, because the choice is a set.
 *
 * A BOX PER AREA RATHER THAN A MULTIPLE SELECT. The kit has no multiple select and should not gain one for
 * this: a set of exclusive-of-nothing choices is what a checkbox group is, every member is visible without
 * opening anything, and a reader can see at a glance that two of eleven Areas are named.
 *
 * The list is only rendered while the scope names Areas. The scope is the statement and this is its membership,
 * so offering the boxes under `forbids after: nothing` would invite a set the api refuses. */

import { Checkbox } from "../../../ui/primitives";
import type { Area } from "../../../api/hooks/useAreas";

export interface ForbiddenAreaChoicesProps {
  readonly areas: readonly Area[];
  readonly chosenIds: readonly string[];
  readonly onToggle: (areaId: string) => void;
}

export function ForbiddenAreaChoices({ areas, chosenIds, onToggle }: ForbiddenAreaChoicesProps) {
  return (
    <div className="flex flex-col gap-1">
      {areas.map((area) => (
        <Checkbox
          key={area.id}
          state={chosenIds.includes(area.id) ? "checked" : "unchecked"}
          onStateChange={() => onToggle(area.id)}
        >
          {area.name}
        </Checkbox>
      ))}
    </div>
  );
}
