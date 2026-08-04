/* Anchor types: the rules in evaluation order, the editor for one type's geometry, and the commitments the
 * rules currently type.
 *
 * REORDERING RE-EVALUATES EXISTING COMMITMENTS, and the panel says so where the controls are. It is not a
 * cosmetic reordering of a list: the first match wins, so moving a rule changes which type every commitment
 * below it holds. The one exception is a retyped occurrence, which was chosen for its series and survives a
 * rule change, and the commitments table is where a reader sees which of theirs those are.
 *
 * THE COMMITMENTS ARE READ OVER A FIXED FORTNIGHT from now, which is the horizon a source projects by default.
 * It is a window rather than everything: the point of the table on this tab is to show what the rules do to
 * real commitments, and a year of them would answer a different question. */

import { EmptyState, PendingState } from "../../../ui/domain";
import { Panel, Pane } from "../../../ui/layout";
import { readingOf } from "../../reading";
import { AnchorTable } from "../components/AnchorTable";
import { AnchorTypeEditor } from "../components/AnchorTypeEditor";
import { AnchorTypeTable } from "../components/AnchorTypeTable";
import { ReadFailure } from "../components/ReadFailure";
import type { Resource } from "../../../contract";
import type { AnchorPage } from "../../../api/hooks/useAnchors";
import type { AnchorType, AnchorTypeEdit } from "../../../api/hooks/useAnchorTypes";
import type { Areas } from "../../../api/hooks/useAreas";
import type { CalendarSource } from "../../../api/hooks/useCalendarSources";
import type { Write } from "../../../api/hooks/useWrite";

export interface AnchorTypesTabProps {
  readonly types: Resource<readonly AnchorType[]>;
  readonly areas: Resource<Areas>;
  readonly sources: Resource<readonly CalendarSource[]>;
  readonly anchors: Resource<AnchorPage>;
  readonly selectedId: string | null;
  readonly onSelect: (anchorTypeId: string) => void;
  readonly onMoveEarlier: (anchorTypeId: string) => void;
  readonly onMoveLater: (anchorTypeId: string) => void;
  readonly write: Write<AnchorTypeEdit>;
  /** The IANA zone the commitment starts are rendered in. */
  readonly timeZone: string;
}

export function AnchorTypesTab({
  types,
  areas,
  sources,
  anchors,
  selectedId,
  onSelect,
  onMoveEarlier,
  onMoveLater,
  write,
  timeZone,
}: AnchorTypesTabProps) {
  const reading = readingOf({
    "anchor types": types,
    Areas: areas,
    "calendar sources": sources,
    commitments: anchors,
  });

  if (reading.status === "loading") {
    return (
      <PendingState
        title="Reading your anchor types"
        detail="The rules in evaluation order, and the commitments they currently type."
      />
    );
  }
  if (reading.status === "error") {
    return (
      <ReadFailure title={`The ${reading.name} could not be read`} problem={reading.problem} />
    );
  }

  const {
    "anchor types": typeList,
    Areas: areaReading,
    "calendar sources": sourceList,
    commitments: page,
  } = reading.data;

  if (typeList.length === 0) {
    return (
      <EmptyState
        title="No anchor type is declared"
        detail={
          "Shadows are declared, never inferred. Until a type matches a commitment, that commitment is " +
          "opaque busy time: no prep, no transit and no recovery are reserved around it."
        }
      />
    );
  }

  const selected = typeList.find((type) => type.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-3.25">
      <Panel
        title="Anchor types"
        headerEnd={<span className="text-eyebrow">rules evaluate in order, first match wins</span>}
        footer="Reordering re-evaluates every existing commitment, because the first matching rule wins. A retyped occurrence keeps the type you chose."
      >
        <AnchorTypeTable
          types={typeList}
          areas={areaReading.areas}
          sources={sourceList}
          selectedId={selectedId}
          onSelect={onSelect}
          onMoveEarlier={onMoveEarlier}
          onMoveLater={onMoveLater}
        />
      </Panel>

      <div className="flex flex-wrap items-start gap-3.25">
        <Pane label="The selected anchor type">
          {selected === null ? (
            <EmptyState
              title="No anchor type is selected"
              detail="Choose a type from the table to read and change the shadow it casts."
            />
          ) : (
            <Panel title={`Edit ${selected.name}`}>
              <AnchorTypeEditor
                key={selected.id}
                type={selected}
                areas={areaReading.areas}
                write={write}
              />
            </Panel>
          )}
        </Pane>
        <Pane label="Commitments these rules type">
          <Panel
            title="Commitments"
            footer={
              page.nextCursor === null
                ? undefined
                : "This fortnight holds more commitments than one page carries, so the table shows the first of them."
            }
          >
            {page.anchors.length === 0 ? (
              <EmptyState
                title="No commitment in the next fortnight"
                detail="A commitment arrives from a calendar source. Until one does, these rules match nothing."
              />
            ) : (
              <AnchorTable anchors={page.anchors} timeZone={timeZone} />
            )}
          </Panel>
        </Pane>
      </div>
    </div>
  );
}
