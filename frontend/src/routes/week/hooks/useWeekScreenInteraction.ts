/* THE WEEK SCREEN'S INTERACTION: selection, the keys, the drag's drop, and the four writes behind them.
 *
 * THE ROUTE IS COMPOSITION AND THIS IS THE BEHAVIOUR. Everything that is not "where does this sit on the page" lives
 * here: what is selected, what the keys do, what a drop sends, and what the last response said.
 *
 * A PIN FROM THE KEYBOARD IS INDISTINGUISHABLE FROM A PIN FROM A DRAG, and it is indistinguishable because it is the
 * same call: `Shift+Up` and `Shift+Down` compute an instant fifteen minutes either way and hand it to the same write
 * the drop hands it to. There is no second path, so there is nothing for the two to disagree about.
 *
 * `j` IS NEXT AND `k` IS PREVIOUS, which is the vi convention rather than the order section 15's table lists them in.
 * The reader's own muscle memory settles it: `j` moves down a list everywhere else they type, and the grid's list runs
 * down the day. `h` and `l` follow the table exactly, previous and next column.
 *
 * SELECTION SURVIVES A REDRAW ONLY WHERE THE BLOCK DOES. A solve landing can remove the selected block, and holding an
 * identifier the week no longer contains would leave the keys acting on nothing: `surviving` is what turns that into a
 * cleared selection rather than a silent no-op. A reason row for a block that no longer exists is the same case, one
 * panel over, and it is answered the same way.
 *
 * THE ZOOM IS SCREEN STATE RATHER THAN A SETTING WRITE. `z` cycles the visible hours within the display's own clamped
 * range, and cycling a stored setting would mean a request per keystroke on the densest surface in the product. The
 * reader's stored value is what the screen opens at, and what they cycle to is theirs until they leave.
 *
 * A LEVEL TRAVELS DOWN AS A PROPOSAL AND COMES BACK AS A READING. Only the grid has a measurement, so only the grid can
 * say which level a display can draw: what this hook holds is the level the reader asked for, and `zoom` is what the
 * grid answered. A surface that states the level reads the answer, because stating the question is how a band comes to
 * claim a level the grid is not drawing.
 *
 * THE DETAIL PANEL IS OPEN WHERE THERE IS ROOM FOR ITS COLUMN AND CLOSED WHERE THERE IS NOT, and the panel is drawn
 * from that state AND the selection rather than from the selection alone. Above --bp-wide the column is reserved and
 * selecting a block is the whole gesture; below it the column would starve the grid of the width a title needs, so the
 * panel starts closed and the rail's own control is the pointer's route to it. `Enter` opens it at either width,
 * `Escape` closes it and clears the selection, and both of those and the rail's control set one state. */

import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { useSWRConfig } from "swr";

import { useKeyBinding } from "../../../lib/keyboard";
import { capturePath, type CaptureInvitation } from "../../../app/capture";
import { weekKey } from "../../../api/keys";
import { useOperation } from "../../../api/hooks/useOperation";
import { usePinning } from "../../../api/hooks/usePins";
import { useWeekSolve } from "../../../api/hooks/useWeek";
import { useWeekWrites } from "../../../api/hooks/useWeekWrites";
import { useServerEvents } from "../../../api/events";
import type {
  BlockDrop,
  BlockStates,
  VerdictTradeoff,
  WeekDay,
  ZoomReport,
} from "../../../ui/domain";
import { isoWeekOf } from "../../today/isoWeek";
import { hasRoomForDetailPanel } from "../panelRoom";
import { stepColumn, stepInColumn, surviving, type Selected } from "../selection";
import { weekAway } from "../weeks";
import type { WeekView } from "../../../api/hooks/useWeek";

const SNAP_MINUTES = 15;
const MILLISECONDS_IN_MINUTE = 60_000;

/* THE LADDER `z` CYCLES, AND WHY IT IS NOT THE WHOLE RANGE. The offerable range is 6 to 24 and its upper end is
 * clamped PER DISPLAY, from a measurement only the grid has: cycling one hour at a time would take nineteen presses
 * to cross it, and cycling the range this route cannot see would mean naming a cap it cannot compute. So the route
 * proposes a level and the grid brings it inside the range its own measured height offers, which is where that
 * arithmetic already lives. A press past this display's cap therefore renders at the cap rather than lying. */
const ZOOM_LADDER = [6, 9, 12, 16, 20, 24] as const;

export interface WeekInteractionInput {
  readonly isoWeek: string;
  /** The columns as drawn, which is what a traversal walks and what a selection is checked against. */
  readonly days: readonly WeekDay[];
  /** The week as last read, or null while it has not arrived. */
  readonly view: WeekView | null;
  /** Today's date in the reader's home zone, so `T` moves to the week holding it. */
  readonly today: string;
  /** The stored visible-hours setting, which is what the screen opens at. */
  readonly visibleHours: number;
}

export interface WeekInteraction {
  readonly selected: Selected | null;
  /** Whether the panel is open. Open where the viewport has room for its column, and never opened by hover. */
  readonly isDetailOpen: boolean;
  /** The level the screen asks the grid for, which the grid brings inside the range its own measurement offers. */
  readonly proposedHours: number;
  /** What the grid answered with, or null before it has measured. What a surface stating the level reads. */
  readonly zoom: ZoomReport | null;
  /** The grid's own answer, handed back once per measurement. */
  readonly onZoom: (report: ZoomReport) => void;
  readonly statesOf: (blockId: string) => BlockStates;
  readonly onSelect: (blockId: string) => void;
  readonly onDrop: (drop: BlockDrop) => void;
  readonly onTogglePin: () => void;
  readonly onApprove: () => void;
  readonly onResolveNow: () => void;
  readonly onCloseDetail: () => void;
  /** The rail's own control, which is what opens the panel on a display with no room for its column. */
  readonly onToggleDetail: () => void;
  /** Requesting a concession, which mutates nothing and dispatches an immediate solve. */
  readonly onPropose: (tradeoff: VerdictTradeoff) => void;
  /** Activating a band's gutter label, which is how an empty slot becomes an invitation to capture. */
  readonly onBandActivate: (bandId: string) => void;
  readonly writes: ReturnType<typeof useWeekWrites>;
  readonly pinning: ReturnType<typeof usePinning>;
  readonly operation: ReturnType<typeof useOperation>;
}

export function useWeekScreenInteraction(input: WeekInteractionInput): WeekInteraction {
  const { isoWeek, days, view, today, visibleHours } = input;
  const navigate = useNavigate();
  const [held, setHeld] = useState<Selected | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(hasRoomForDetailPanel);
  const [zoomHours, setZoomHours] = useState<number | null>(null);
  const [zoom, setZoom] = useState<ZoomReport | null>(null);

  const operation = useOperation(isoWeek);
  const pinning = usePinning(isoWeek, view?.inputVersion ?? 0, operation.track);
  const writes = useWeekWrites(isoWeek, operation.track);
  const solve = useWeekSolve();

  /* A conflict is the ONE condition in this product that pushes a notification, so a pushed one reads the week again:
   * the banner and the block's own oxide rule are both drawn from the week's `conflicts`, and the event carries no
   * plan document by design. Nothing else on the stream concerns this screen that `useOperation` does not answer. */
  const { mutate } = useSWRConfig();
  useServerEvents(
    useCallback(
      (event) => {
        if (event.type !== "conflict") return;
        if (event.data.isoWeek !== isoWeek) return;
        void mutate(weekKey(isoWeek));
      },
      [isoWeek, mutate],
    ),
  );

  const selected = surviving(days, held);
  const goTo = (isoWeekTarget: string): void => {
    void navigate(`/week?week=${isoWeekTarget}`);
  };

  const select = useCallback((next: Selected | null) => {
    setHeld(next);
  }, []);

  const move = (direction: 1 | -1): void => {
    select(stepInColumn(days, selected, direction));
  };
  const acrossColumns = (direction: 1 | -1): void => {
    select(stepColumn(days, selected, direction));
  };

  const pinAt = (blockId: string, startMs: number): void => {
    void pinning.pin.submit({ blockId, startMs });
  };

  const nudge = (steps: 1 | -1): void => {
    const found = blockOf(days, selected);
    if (found === null) return;
    pinAt(found.blockId, found.startMs + steps * SNAP_MINUTES * MILLISECONDS_IN_MINUTE);
  };

  const togglePin = (): void => {
    const found = blockOf(days, selected);
    if (found === null || view === null) return;
    if (!found.isPinned) {
      /* `p` on an unpinned block pins it where it already is, which is the one pin a drop can never make: a drag onto
       * the same quarter hour issues no request, and this is the reader asking for exactly that. */
      pinAt(found.blockId, found.startMs);
      return;
    }
    const pin = view.pins.find((each) => each.blockId === found.blockId);
    if (pin === undefined) return;
    void pinning.unpin.submit({ pinId: pin.id, blockId: found.blockId });
  };

  useKeyBinding({ key: "j" }, () => {
    move(1);
  });
  useKeyBinding({ key: "k" }, () => {
    move(-1);
  });
  useKeyBinding({ key: "l" }, () => {
    acrossColumns(1);
  });
  useKeyBinding({ key: "h" }, () => {
    acrossColumns(-1);
  });
  useKeyBinding({ key: "[" }, () => {
    goTo(weekAway(isoWeek, -1));
  });
  useKeyBinding({ key: "]" }, () => {
    goTo(weekAway(isoWeek, 1));
  });
  useKeyBinding({ key: "T" }, () => {
    const week = isoWeekOf(today);
    if (week !== null) goTo(week);
  });
  useKeyBinding({ key: "z" }, () => {
    setZoomHours(nextZoom(zoomHours ?? visibleHours));
  });
  useKeyBinding({ key: "p" }, togglePin);
  useKeyBinding({ key: "Enter" }, () => {
    if (selected !== null) setIsDetailOpen(true);
  });
  useKeyBinding({ key: "A", withShift: true }, () => {
    void writes.approve.submit(undefined);
  });
  useKeyBinding({ key: "ArrowUp", withShift: true }, () => {
    nudge(-1);
  });
  useKeyBinding({ key: "ArrowDown", withShift: true }, () => {
    nudge(1);
  });
  useKeyBinding({ key: "Escape" }, () => {
    setIsDetailOpen(false);
    select(null);
  });

  const proposalTargets = useMemo(() => targetsOf(view), [view]);
  const conflicted = useMemo(() => conflictedOf(view), [view]);

  const statesOf = useCallback(
    (blockId: string): BlockStates => ({
      isSelected: selected?.blockId === blockId,
      isConflicted: conflicted.has(blockId),
      isProposalTarget: proposalTargets.has(blockId),
    }),
    [conflicted, proposalTargets, selected],
  );

  return {
    selected,
    isDetailOpen,
    proposedHours: zoomHours ?? visibleHours,
    zoom,
    onZoom: setZoom,
    statesOf,
    onSelect: (blockId) => {
      const date = days.find((day) => day.blocks.some((block) => block.id === blockId))?.date;
      if (date === undefined) return;
      select({ date, blockId });
      setIsDetailOpen(true);
    },
    onDrop: (drop: BlockDrop) => {
      pinAt(drop.blockId, drop.startMs);
    },
    onTogglePin: togglePin,
    onApprove: () => {
      void writes.approve.submit(undefined);
    },
    onResolveNow: () => {
      void solve.submit({ isoWeek, isImmediate: true });
    },
    onCloseDetail: () => {
      setIsDetailOpen(false);
    },
    onToggleDetail: () => {
      setIsDetailOpen((open) => !open);
    },
    onPropose: (tradeoff) => {
      void writes.requestTradeoff.submit({ kind: tradeoff.kind, targetId: tradeoff.targetId });
    },
    onBandActivate: (bandId) => {
      const slot = emptySlotOf(view, bandId);
      if (slot === null) return;
      /* CAPTURE PREFILLED FROM THE SLOT, stated in the URL rather than in a call. The capture surface belongs to the
       * Backlog screen, which is where a task is authored; what this screen knows is the slot's Area, the duration a
       * task would need to fit it exactly, and the window the work should prefer. Naming those in the URL is the same
       * seam a mode uses on this product's other screens: it survives a reload and it can be linked.
       *
       * THE PATH IS COMPOSED WHERE IT IS READ, so a parameter cannot be renamed at one end alone. */
      void navigate(capturePath(slot));
    },
    writes,
    pinning,
    operation,
  };
}

/** The selected block's own start as an instant, which is what a fifteen-minute nudge is measured from. */
function blockOf(
  days: readonly WeekDay[],
  selected: Selected | null,
): { blockId: string; startMs: number; isPinned: boolean } | null {
  if (selected === null) return null;
  const day = days.find((each) => each.date === selected.date);
  const block = day?.blocks.find((each) => each.id === selected.blockId);
  if (day === undefined || block === undefined) return null;
  return {
    blockId: block.id,
    startMs: day.startMs + block.span.startMin * MILLISECONDS_IN_MINUTE,
    isPinned: block.isPinned,
  };
}

/** Every block the pending proposal would move or drop, which is what draws with no fill. */
function targetsOf(view: WeekView | null): ReadonlySet<string> {
  const proposal = view?.proposal ?? null;
  if (proposal === null) return new Set();
  return new Set(
    [...proposal.moved, ...proposal.removed, ...proposal.added].map((change) => change.blockId),
  );
}

/** Every block an unanswered overlap landed on, which is what takes the oxide left rule. */
function conflictedOf(view: WeekView | null): ReadonlySet<string> {
  if (view === null) return new Set();
  return new Set(
    view.conflicts.filter((each) => each.resolvedAt === null).map((each) => each.blockId),
  );
}

/** The next level of the ladder, wrapping at the top, from whatever the screen is currently showing. */
function nextZoom(hours: number): number {
  const at = ZOOM_LADDER.findIndex((level) => level >= hours);
  return ZOOM_LADDER[(at + 1) % ZOOM_LADDER.length] ?? ZOOM_LADDER[0];
}

/**
 * The empty slot a band's identifier names, with the estimate a task would need to fit it exactly.
 *
 * The identifier is the one `bands.ts` composes, which is the Area and the slot's own start: a slot has no id on the
 * wire, and the pair is what a week's slots are unique by.
 */
function emptySlotOf(view: WeekView | null, bandId: string): CaptureInvitation | null {
  if (view === null || view.live === null) return null;
  const found = view.live.emptySlots.find(
    (slot) => `empty-slot:${slot.areaId}:${slot.interval.start}` === bandId,
  );
  if (found === undefined) return null;
  return {
    areaId: found.areaId,
    estimateMinutes: Math.round(
      (Date.parse(found.interval.end) - Date.parse(found.interval.start)) / MILLISECONDS_IN_MINUTE,
    ),
    preferredWindow: { from: found.interval.start, to: found.interval.end },
  };
}
