/* Editing one anchor type's geometry: what it casts before, around and after a commitment.
 *
 * THE REFUSAL IS THE FEATURE HERE. A prep lead that leaves prep still running when the outbound leg leaves
 * produces a shadow that cannot be laid out, and the api refuses it at the boundary naming which of the three
 * members to change. That notice is rendered inline, in amber, at the top of this panel and again on the row
 * that owns the member, so the collision surfaces while the reader is editing the thing that is wrong rather
 * than at solve time as a plan that will not compute. This form does not re-check that arithmetic: a second
 * copy of it in the browser is a second thing that can drift from the constraint the table holds.
 *
 * AN AREA IS WHAT MAKES A BUFFER A BLOCK. Prep and transit with an Area generate blocks that consume that
 * Area's budget, appear in the ledger and project to the write target; without one they generate forbidden
 * windows, because a buffer with no Area has no budget to consume. So the Area control offers `no Area` as a
 * real choice with its consequence stated, not as an empty value.
 *
 * A NULL TRANSIT LEAD IS THE ABUTTING DEFAULT, not zero: leave exactly late enough to arrive on time. It is a
 * checkbox rather than a magic figure, because there is no number that means "abuts". */

import { useState } from "react";

import { NoticeCard } from "../../../ui/domain";
import { FormRow } from "../../../ui/layout";
import { Button, Checkbox, Radio, Select } from "../../../ui/primitives";
import {
  anchorTypeDraftFrom,
  anchorTypeProposalFrom,
  type AnchorTypeDraft,
  type PostScope,
} from "../anchorTypeDraft";
import { POST_SCOPE_LABELS, POST_SCOPE_QUESTION } from "../labels";
import { messageFor, rejectionNotice } from "../rejection";
import { ForbiddenAreaChoices } from "./ForbiddenAreaChoices";
import { MinutesRow } from "./MinutesRow";
import type { Area } from "../../../api/hooks/useAreas";
import type { AnchorType, AnchorTypeEdit } from "../../../api/hooks/useAnchorTypes";
import type { Write } from "../../../api/hooks/useWrite";

/* A select hands back a string, so the absent Area needs a value of its own. No identifier can collide with it:
 * every Area identifier is a UUID. */
const NO_AREA = "no-area";

const LEAD_MAXIMUM = 10080;
const SPAN_MAXIMUM = 1440;

const SCOPE_OPTIONS = [
  { value: "none", label: POST_SCOPE_LABELS.none },
  { value: "all", label: POST_SCOPE_LABELS.all },
  { value: "areas", label: POST_SCOPE_LABELS.areas },
];

const SCOPES: readonly PostScope[] = ["none", "all", "areas"];

export interface AnchorTypeEditorProps {
  readonly type: AnchorType;
  readonly areas: readonly Area[];
  readonly write: Write<AnchorTypeEdit>;
}

export function AnchorTypeEditor({ type, areas, write }: AnchorTypeEditorProps) {
  /* Keyed by the type's identifier at the call site, so choosing another type mounts a fresh draft rather than
   * showing one type's geometry under another's name. */
  const [draft, setDraft] = useState<AnchorTypeDraft>(() => anchorTypeDraftFrom(type));
  const proposal = anchorTypeProposalFrom(draft);
  const isIncomplete = proposal.status === "incomplete";
  /* Read into a name, because a narrowing on a property does not survive into the row's own callback. */
  const transitLead = draft.transitLeadMinutes;

  const areaOptions = [
    { value: NO_AREA, label: "no Area \u00B7 a forbidden window rather than a block" },
    ...areas.map((area) => ({ value: area.id, label: area.name })),
  ];
  const areaValue = (areaId: string | null): string => areaId ?? NO_AREA;
  const areaChoice = (value: string): string | null => (value === NO_AREA ? null : value);

  return (
    <div className="flex flex-col gap-3.25">
      {write.problem === null ? null : (
        <NoticeCard
          notice={rejectionNotice({
            id: "anchor-type-edit",
            problem: write.problem,
            stillWorks: "this type as it was, and every other anchor type unchanged",
          })}
        />
      )}

      <MinutesRow
        label="Prep lead"
        hint="how long before the commitment prep starts"
        error={messageFor(write.problem, "prepLeadMinutes")}
        min={0}
        max={LEAD_MAXIMUM}
        unit="minutes before"
        value={draft.prepLeadMinutes}
        onValueChange={(prepLeadMinutes) =>
          setDraft((previous) => ({ ...previous, prepLeadMinutes }))
        }
      />

      <MinutesRow
        label="Prep"
        hint="zero means no prep, whatever the lead says"
        error={messageFor(write.problem, "prepDurationMinutes")}
        min={0}
        max={SPAN_MAXIMUM}
        unit="minutes long"
        value={draft.prepDurationMinutes}
        onValueChange={(prepDurationMinutes) =>
          setDraft((previous) => ({ ...previous, prepDurationMinutes }))
        }
      />

      <FormRow label="Prep Area" error={messageFor(write.problem, "prepAreaId")}>
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={areaValue(draft.prepAreaId)}
            onValueChange={(value) =>
              setDraft((previous) => ({ ...previous, prepAreaId: areaChoice(value) }))
            }
            options={areaOptions}
          />
        )}
      </FormRow>

      <Checkbox
        state={transitLead === null ? "checked" : "unchecked"}
        onStateChange={(next) =>
          setDraft((previous) => ({
            ...previous,
            /* Unchecking restores the figure the abutting default stands for, which is the journey's own duration:
             * leaving exactly late enough to arrive on time IS a lead equal to the duration. Any other starting
             * figure would move the leg the moment a reader stopped abutting. */
            transitLeadMinutes: next === "checked" ? null : previous.transitDurationMinutes,
          }))
        }
      >
        Leave exactly late enough to arrive on time
      </Checkbox>

      {transitLead === null ? null : (
        <MinutesRow
          label="Transit lead"
          hint="a larger lead arrives early and leaves a deliberate gap"
          error={messageFor(write.problem, "transitLeadMinutes")}
          min={0}
          max={LEAD_MAXIMUM}
          unit="minutes before"
          value={transitLead}
          onValueChange={(transitLeadMinutes) =>
            setDraft((previous) => ({ ...previous, transitLeadMinutes }))
          }
        />
      )}

      <MinutesRow
        label="Transit out"
        hint="the outbound journey. Zero means no outbound leg"
        error={messageFor(write.problem, "transitDurationMinutes")}
        min={0}
        max={SPAN_MAXIMUM}
        unit="minutes long"
        value={draft.transitDurationMinutes}
        onValueChange={(transitDurationMinutes) =>
          setDraft((previous) => ({ ...previous, transitDurationMinutes }))
        }
      />

      <MinutesRow
        label="Transit back"
        hint="zero means no return leg, which the outbound duration does not imply"
        error={messageFor(write.problem, "returnTransitMinutes")}
        min={0}
        max={SPAN_MAXIMUM}
        unit="minutes long"
        value={draft.returnTransitMinutes}
        onValueChange={(returnTransitMinutes) =>
          setDraft((previous) => ({ ...previous, returnTransitMinutes }))
        }
      />

      <FormRow label="Transit Area" error={messageFor(write.problem, "transitAreaId")}>
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={areaValue(draft.transitAreaId)}
            onValueChange={(value) =>
              setDraft((previous) => ({ ...previous, transitAreaId: areaChoice(value) }))
            }
            options={areaOptions}
          />
        )}
      </FormRow>

      <MinutesRow
        label="Post buffer"
        hint="measured from the commitment's end, never from the end of a return leg"
        error={messageFor(write.problem, "postBufferMinutes")}
        min={0}
        max={SPAN_MAXIMUM}
        unit="minutes after"
        value={draft.postBufferMinutes}
        onValueChange={(postBufferMinutes) =>
          setDraft((previous) => ({ ...previous, postBufferMinutes }))
        }
      />

      {/* The three-way choice is rendered as well as announced, because the words ARE the control: a reader
       * deciding what a recovery window forbids has to see the question. The kit's radio group takes its name
       * as a string, so a screen reader hears it twice, which ticket 1240 closes. */}
      <p className="text-label tracking-label uppercase text-text-muted">{POST_SCOPE_QUESTION}</p>
      <Radio
        label={POST_SCOPE_QUESTION}
        value={draft.postScope}
        onValueChange={(value) =>
          setDraft((previous) => ({
            ...previous,
            postScope: SCOPES.find((scope) => scope === value) ?? "none",
          }))
        }
        options={SCOPE_OPTIONS}
      />

      {draft.postScope !== "areas" ? null : (
        <FormRow
          label="Forbidden"
          hint={isIncomplete ? proposal.reason : "the Areas this window forbids"}
          error={messageFor(write.problem, "forbiddenAreaIds")}
        >
          {() => (
            <ForbiddenAreaChoices
              areas={areas}
              chosenIds={draft.forbiddenAreaIds}
              onToggle={(areaId) =>
                setDraft((previous) => ({
                  ...previous,
                  forbiddenAreaIds: previous.forbiddenAreaIds.includes(areaId)
                    ? previous.forbiddenAreaIds.filter((chosen) => chosen !== areaId)
                    : [...previous.forbiddenAreaIds, areaId],
                }))
              }
            />
          )}
        </FormRow>
      )}

      <Button
        isDisabled={isIncomplete}
        onClick={() => {
          if (proposal.status === "declarable") void write.submit(proposal.body);
        }}
      >
        Save the anchor type
      </Button>
    </div>
  );
}
