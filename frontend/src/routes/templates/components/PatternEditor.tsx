/* Declaring the week pattern: seven weekdays, one day type each, replaced whole.
 *
 * THE CONTROL CANNOT SUBMIT A PARTIAL MAPPING, and the refusal is not a validation message after the fact: the
 * button is inert while any weekday names no day type, and the panel says which weekdays are still to choose.
 * A pattern is replaced whole because a weekday with no day type materializes nothing, so there is no merge
 * rule a partial request could mean.
 *
 * CADENCE IS NOT EXPRESSIBLE HERE, and the panel says so where a reader would otherwise look for it. Cadence
 * lives on a habit: `4 times a week` is a property of going to the gym, not of Tuesday, and a template that
 * carried a repeat rule would need composition and override rules against the habit's own for no added
 * expressiveness. The api refuses a cadence member on every template shape, so this statement is the visible
 * half of a boundary that already holds. */

import { useState } from "react";

import { NoticeCard } from "../../../ui/domain";
import { FormRow, Panel } from "../../../ui/layout";
import { Button, Select } from "../../../ui/primitives";
import { WEEKDAY_KEYS, weekdayLabel } from "../labels";
import {
  patternBodyFrom,
  patternDraftFrom,
  unmappedWeekdays,
  type PatternDraft,
} from "../patternDraft";
import { rejectionNotice } from "../rejection";
import type { DayType } from "../../../api/hooks/useTemplates";
import type { WeekPattern, WeekPatternBody } from "../../../api/hooks/useWeekPattern";
import type { Write } from "../../../api/hooks/useWrite";

export interface PatternEditorProps {
  readonly pattern: WeekPattern | null;
  readonly dayTypes: readonly DayType[];
  readonly write: Write<WeekPatternBody>;
}

export function PatternEditor({ pattern, dayTypes, write }: PatternEditorProps) {
  const [draft, setDraft] = useState<PatternDraft>(() => patternDraftFrom(pattern));
  const unmapped = unmappedWeekdays(draft);
  const body = patternBodyFrom(draft);

  const options = dayTypes.map((dayType) => ({ value: dayType.id, label: dayType.name }));

  return (
    <Panel title="Declare the week pattern">
      <div className="flex flex-col gap-3.25">
        {write.problem === null ? null : (
          <NoticeCard
            notice={rejectionNotice({
              id: "week-pattern",
              problem: write.problem,
              stillWorks: "the pattern the plan is built from, unchanged",
            })}
          />
        )}

        {WEEKDAY_KEYS.map((weekday) => (
          <FormRow key={weekday} label={weekdayLabel(weekday)} isRequired>
            {(field) => (
              <Select
                id={field.id}
                describedBy={field.describedBy}
                value={draft[weekday] ?? ""}
                onValueChange={(dayTypeId) =>
                  setDraft((previous) => ({ ...previous, [weekday]: dayTypeId }))
                }
                options={options}
                placeholder="choose a day type"
              />
            )}
          </FormRow>
        ))}

        <p className="text-eyebrow text-text-muted">
          A pattern is replaced whole, so every weekday names a day type before it can be declared.
          Cadence is not expressible here: it lives on a habit, which is why nothing on this screen
          repeats a template.
        </p>

        {unmapped.length === 0 ? null : (
          <p className="text-eyebrow text-text-muted">
            Still to choose: {unmapped.map((weekday) => weekdayLabel(weekday)).join(", ")}.
          </p>
        )}

        <Button
          isDisabled={body === null}
          onClick={() => {
            if (body !== null) void write.submit(body);
          }}
        >
          Declare the pattern
        </Button>
      </div>
    </Panel>
  );
}
