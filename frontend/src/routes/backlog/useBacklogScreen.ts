/* THE BACKLOG SCREEN'S STATE: which filters are on, which column the rows run by, and the one write the table
 * makes.
 *
 * THE FILTERS ARE THE READ AND THE SORT IS NOT. A filter is a query parameter the route serves, so changing one
 * changes the request and the key it caches under; the order is the screen's, because `GET /api/v1/tasks` serves
 * the backlog oldest first and its repository states why: the order a backlog is read in needs a deadline, a
 * priority and the verdict's shortfalls to decide, and persistence owes only an order that does not change
 * between two identical reads.
 *
 * TWO READS, JOINED HERE. The backlog is the rows, and the Areas are where a chip's assigned pigment and an
 * Area's name come from: the wire carries an Area's identifier on a task and not its pigment, so the pair is
 * joined by the screen rather than by a row that fetched.
 *
 * NOTHING POLLS AND NOTHING IS PUSHED. The at-risk marking is recomputed by the api on every read, so it is
 * current whenever the plan changed and current again on the next read after time alone moved the verdict.
 * What re-reads the list is a write on it, which is the only moment this client knows something moved.
 *
 * NOW IS READ ONCE PER RENDER, not on a timer, which is the same rule the Week screen's now rule follows: a
 * deadline crossing while the screen sits open is seen at the next redraw, and a clock that advanced on its own
 * would be the one moving thing in a product whose motion is zero. */

import { useState } from "react";

import { useAreas, type Areas } from "../../api/hooks/useAreas";
import {
  useBacklog,
  useTaskCompletion,
  type Backlog,
  type BacklogFilters,
  type BacklogTask,
} from "../../api/hooks/useBacklog";
import { useSettings } from "../../api/hooks/useSettings";
import { areaPigment, type AreaPigment, type TableSort } from "../../ui/domain";
import type { Problem, Resource } from "../../contract";
import { DEFAULT_FILTERS } from "./filters";
import { DEFAULT_SORT, ordered } from "./order";

export interface BacklogArea {
  readonly name: string;
  readonly pigment: AreaPigment;
}

/** What the screen renders once both reads have landed. */
export interface BacklogScreen {
  readonly backlog: Backlog;
  /** The rows in the order the sort asks for, which is what the table draws. */
  readonly rows: readonly BacklogTask[];
  readonly areas: ReadonlyMap<string, BacklogArea>;
}

export interface BacklogState {
  /** Loading until BOTH reads have landed, and in error when either failed. */
  readonly reading: Resource<BacklogScreen>;
  /** Which of the two reads failed, for the surface that names it. */
  readonly failed: string | null;
  readonly filters: BacklogFilters;
  readonly sort: TableSort;
  /** The reader's own home zone, which every deadline on screen is read in. */
  readonly zone: string;
  /** The instant this render was drawn at. */
  readonly nowMs: number;
  /** The last completion the api refused, or null. */
  readonly completionRefusal: Problem | null;
  /** The task most recently completed, so the screen can state what happens to its blocks. */
  readonly completed: string | null;
}

export interface BacklogActions {
  readonly onFiltersChange: (next: BacklogFilters) => void;
  readonly onSortChange: (next: TableSort) => void;
  readonly onComplete: (taskId: string) => void;
}

/** Which read failed and what it said, or null while neither has. */
function failureOf(
  backlog: Resource<Backlog>,
  areas: Resource<Areas>,
): { readonly name: string; readonly problem: Problem } | null {
  if (backlog.status === "error") return { name: "backlog", problem: backlog.problem };
  if (areas.status === "error") return { name: "Areas", problem: areas.problem };
  return null;
}

/**
 * The two reads as one reading: loading until both have landed, in error when either failed.
 *
 * One reading rather than two, because the screen has one table and a table cannot draw two thirds of its Area
 * column: a row whose Area is not named yet would draw a chip that identifies nothing.
 */
function readingOf(
  backlog: Resource<Backlog>,
  areas: Resource<Areas>,
  screen: BacklogScreen | null,
): Resource<BacklogScreen> {
  const failure = failureOf(backlog, areas);
  if (failure !== null) return { status: "error", problem: failure.problem };
  if (screen === null) return { status: "loading" };
  return { status: "ready", data: screen };
}

export function useBacklogScreen(): BacklogState & BacklogActions {
  const [filters, setFilters] = useState<BacklogFilters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<TableSort>(DEFAULT_SORT);
  const [completed, setCompleted] = useState<string | null>(null);

  const backlog = useBacklog(filters);
  const areas = useAreas();
  const settings = useSettings();
  const completion = useTaskCompletion();

  const zone = settings.status === "ready" ? settings.data.homeZone : "UTC";
  const named = new Map<string, BacklogArea>(
    (areas.status === "ready" ? areas.data.areas : []).map((area) => [
      area.id,
      { name: area.name, pigment: areaPigment(area.pigmentIndex) },
    ]),
  );

  const screen: BacklogScreen | null =
    backlog.status === "ready" && areas.status === "ready"
      ? {
          backlog: backlog.data,
          rows: ordered(backlog.data.tasks, sort, (areaId) => named.get(areaId)?.name ?? ""),
          areas: named,
        }
      : null;

  return {
    reading: readingOf(backlog, areas, screen),
    failed: failureOf(backlog, areas)?.name ?? null,
    filters,
    sort,
    zone,
    nowMs: Date.now(),
    completionRefusal: completion.problem,
    completed,
    onFiltersChange: (next: BacklogFilters) => {
      /* The notice is about a row that left THIS list. Narrowing to another one, or ordering it differently, is
       * the reader moving on, and a confirmation that outlived what it confirmed would sit on the screen for
       * the life of the mount. */
      setCompleted(null);
      setFilters(next);
    },
    onSortChange: (next: TableSort) => {
      setCompleted(null);
      setSort(next);
    },
    onComplete: (taskId: string) => {
      void completion.submit(taskId).then((applied) => {
        setCompleted(applied ? taskId : null);
      });
    },
  };
}
