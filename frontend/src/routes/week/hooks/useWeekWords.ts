/* EVERY WORD THIS SCREEN RENDERS, COMPOSED IN ONE PLACE.
 *
 * THE ROUTE IS COMPOSITION AND THE INTERACTION IS BEHAVIOUR, so the narrowing sits between them: a wire verdict
 * becoming a panel verdict, six clause kinds becoming labelled rows, a conflict becoming a banner and three answers,
 * and a refusal becoming a notice. None of it is state and none of it is a component, which is why it is a hook
 * returning readings rather than either.
 *
 * ONE ZONE FOR EVERY READING ON THE SCREEN. The week's own days carry the zone in force on each date, and the head
 * zone is what a deadline and an approval date are read in: a reader east of their own plan would otherwise see a
 * Friday deadline reported as Saturday.
 *
 * A CONFLICT'S THREE ANSWERS ARE STATED AND NONE IS TAKEN. `move the block` releases the pin where there is one and
 * marks the block ineligible where there is not, which is one route either way; `keep both` records the answer and
 * leaves the overlap; `retype the anchor` is the third. Nothing is moved before one is chosen. */

import { useMemo } from "react";

import { objectiveDeltaOf, definitionRowsOf, reasonRowsOf } from "../reasons";
import { concessionsOf, panelVerdictOf, stripVerdictOf } from "../verdict";
import { conflictNotice, refusedNotice, solveFailedNotice } from "../notices";
import { clockReading, readingsIn, type WeekReadingsContext } from "../readings";
import type { BannerConflict } from "../components/WeekHead";
import type { WeekScreenState } from "../useWeekScreen";
import type { WeekView } from "../../../api/hooks/useWeek";
import type { WeekInteraction } from "./useWeekScreenInteraction";
import type { LabelledRow, Notice, PanelVerdict, VerdictConcession } from "../../../ui/domain";

/** What the detail panel renders about the selected block, or null when nothing is selected. */
export interface DetailReading {
  readonly title: string;
  readonly definitionRows: readonly LabelledRow[];
  readonly reasonRows: readonly LabelledRow[];
  readonly cost: string | null;
  readonly actions: readonly { readonly label: string; readonly onSelect: () => void }[];
}

export interface WeekWords {
  readonly verdict: PanelVerdict | null;
  readonly concessions: readonly VerdictConcession[];
  readonly stripVerdict: { readonly headline: string; readonly detail: string } | null;
  readonly notices: readonly Notice[];
  readonly conflicts: readonly BannerConflict[];
  readonly detail: DetailReading | null;
}

export interface WeekWordsInput {
  readonly screen: WeekScreenState;
  readonly interaction: WeekInteraction;
  readonly homeZone: string;
}

const TEMPLATES_PATH = "/templates";

export function useWeekWords({ screen, interaction, homeZone }: WeekWordsInput): WeekWords {
  const view = viewOf(screen);
  const areaNames = screen.status === "ready" ? screen.areaNames : EMPTY_NAMES;
  /* THE HEAD ZONE OF THE WEEK, which is Monday's: a week's dates are keyed in order, and a reading that picked a zone
   * per row would report one week in two zones the week a reader travels mid-week. */
  const zone = view === null ? homeZone : (zoneOf(view.zoneByDate) ?? homeZone);

  const context = useMemo<WeekReadingsContext>(
    () => readingsIn(zone, areaNames),
    [areaNames, zone],
  );

  /* THE PIN RESPONSE'S VERDICT WINS OVER THE READ'S, and only because it is strictly newer: it was computed against
   * the version that pin created, and a response for an older version never reaches here at all. */
  const wire = interaction.pinning.live?.verdict ?? view?.verdict ?? null;
  const verdict = wire === null ? null : panelVerdictOf(wire, context);
  const concessions = view === null ? [] : concessionsOf(view.adjustments, context);

  const notices: Notice[] = [];
  const failure = interaction.operation.failure;
  if (failure !== null) notices.push(solveFailedNotice(failure.operationId, failure.statement));
  for (const problem of refusals(interaction)) notices.push(refusedNotice(problem));

  return {
    verdict,
    concessions,
    stripVerdict: verdict === null ? null : stripVerdictOf(verdict, concessions.length),
    notices,
    conflicts: bannersOf(view, interaction, zone),
    detail: detailOf(screen, interaction, context),
  };
}

/** Every refusal standing on the screen, in the order the writes are made. One notice each. */
function refusals(interaction: WeekInteraction) {
  return [
    interaction.pinning.problem,
    interaction.writes.approve.problem,
    interaction.writes.requestTradeoff.problem,
    interaction.writes.resolveConflict.problem,
    interaction.writes.rejectMove.problem,
  ].filter((problem) => problem !== null);
}

function bannersOf(
  view: WeekView | null,
  interaction: WeekInteraction,
  zone: string,
): BannerConflict[] {
  if (view === null) return [];
  return view.conflicts
    .filter((conflict) => conflict.resolvedAt === null)
    .map((conflict) => ({
      id: conflict.id,
      notice: conflictNotice(
        conflict.id,
        `A commitment overlaps this block from ${clockReading(conflict.overlap.start, zone)} to ${clockReading(conflict.overlap.end, zone)}. Nothing has been moved.`,
        conflict.blockId,
      ),
      answers: [
        {
          label: "Move the block",
          onSelect: () => {
            void interaction.writes.resolveConflict.submit({
              conflictId: conflict.id,
              resolution: "moved",
            });
          },
        },
        {
          label: "Keep both",
          onSelect: () => {
            void interaction.writes.resolveConflict.submit({
              conflictId: conflict.id,
              resolution: "kept-both",
            });
          },
        },
        {
          label: "Retype the commitment",
          onSelect: () => {
            void interaction.writes.resolveConflict.submit({
              conflictId: conflict.id,
              resolution: "retyped",
              anchorTypeId: null,
            });
          },
        },
      ],
      /* A MATERIALIZED TEMPLATE ENTRY OFFERS TWO PATHS AND CHOOSES NEITHER: pin this occurrence elsewhere, which is
       * `Move the block` above, or edit the template that produced it, which is a different screen. */
      templatePath: conflict.binding.kind === "template_entry" ? TEMPLATES_PATH : undefined,
    }));
}

/** Narrowed once so the banner builder reads a view or a null and not a screen state. */
function viewOf(screen: WeekScreenState): WeekView | null {
  return screen.status === "ready" ? screen.view : null;
}

/** The zone the week's first date is in, which is the one every reading on the screen is taken in. */
function zoneOf(zoneByDate: Readonly<Record<string, string>>): string | null {
  const first = Object.keys(zoneByDate).toSorted().at(0);
  return first === undefined ? null : (zoneByDate[first] ?? null);
}

const EMPTY_NAMES: ReadonlyMap<string, string> = new Map();

function detailOf(
  screen: WeekScreenState,
  interaction: WeekInteraction,
  context: WeekReadingsContext,
): DetailReading | null {
  const view = viewOf(screen);
  const selected = interaction.selected;
  if (view === null || view.live === null || selected === null) return null;
  const block = view.live.blocks.find((each) => each.id === selected.blockId);
  /* A REASON ROW FOR A BLOCK THE PLAN NO LONGER HOLDS IS NOT DRAWN. A solve landing can remove the selected block, and
   * a panel that kept describing it would state a placement that no longer exists. */
  if (block === undefined) return null;

  return {
    title: block.title,
    definitionRows: definitionRowsOf(block, context),
    reasonRows: reasonRowsOf(block.reason, context),
    cost: objectiveDeltaOf(block),
    actions: block.pinned
      ? [{ label: "Unpin", onSelect: interaction.onTogglePin }]
      : [{ label: "Pin here", onSelect: interaction.onTogglePin }],
  };
}
