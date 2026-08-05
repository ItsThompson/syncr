/* The setup minimum, read from the resources the api answers with.
 *
 * ONE READING, TWO CONSUMERS. The root redirect sends a reader to setup when the minimum does not exist, and the
 * setup ledger says which of the two is missing. Deriving that in both places would be two definitions of the same
 * word, and the one in the redirect is the one nobody would notice going wrong.
 *
 * IT IS A RESOURCE OF ITS OWN SHAPE rather than four resources a caller narrows itself. A caller asking "may this
 * tenant be planned for" wants one answer with one loading state, and a redirect in particular cannot act on three
 * quarters of one.
 *
 * A FAILED READ IS NOT A MISSING MINIMUM. A reader whose Areas could not be fetched has not lost their Areas, and
 * sending them to setup on a 503 would be the product telling them to declare what they already have. The redirect
 * treats a refusal as "carry on to the week", where the week's own empty state states the reason the api gives. */

import { useAreas } from "../../api/hooks/useAreas";
import { useCalendarSources } from "../../api/hooks/useCalendarSources";
import { useDayShapes } from "../../api/hooks/useTemplates";
import { useWeekPattern } from "../../api/hooks/useWeekPattern";
import { readingOf } from "../reading";
import { isMinimumDeclared, type SetupReads } from "./steps";
import type { Resource } from "../../contract";

/** Every read the setup ledger and the root redirect are decided from, as one resource. */
export function useSetupReads(): Resource<SetupReads> {
  const areas = useAreas();
  const shapes = useDayShapes();
  const pattern = useWeekPattern();
  const sources = useCalendarSources();

  const reading = readingOf({ areas, shapes, pattern, sources });
  if (reading.status === "loading") return { status: "loading" };
  if (reading.status === "error") return { status: "error", problem: reading.problem };

  const target = reading.data.sources.find((source) => source.writeTarget != null) ?? null;
  return {
    status: "ready",
    data: {
      sourceCount: reading.data.sources.length,
      areaCount: reading.data.areas.areas.length,
      dayShapeCount: reading.data.shapes.length,
      isPatternDeclared: reading.data.pattern !== null,
      writeTargetName: target?.writeTarget?.calendarName ?? null,
    },
  };
}

/** Whether the reader should be sent to setup: only when the reads landed and the minimum is absent. */
export function isSetupRequired(reads: Resource<SetupReads>): boolean {
  return reads.status === "ready" && !isMinimumDeclared(reads.data);
}
