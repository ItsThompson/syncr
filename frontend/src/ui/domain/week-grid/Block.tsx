/* THE BLOCK. One rectangle answering three questions: what is this, whose time is it, and may it move.
 *
 * Every state channel it carries is assigned in `block.css`, and the two channels it SHARES with the rest of the
 * kit -- hover's fill and the reserved 3px left rule -- arrive by composing `.state-row` rather than by a second
 * definition of either.
 *
 * THE TITLE IS AVAILABLE AT EVERY TIER, so the sliver tier is never a dead end. Below the label tiers the visible
 * title is not rendered at all, and the block's accessible name still carries it, along with the Area's name
 * where it has one: the ramp repeats past twelve Areas and forced-colors mode drops the pigment entirely, so the
 * name is what identity actually rests on.
 *
 * THE VISIBLE TITLE IS NOT RENDERED RATHER THAN HIDDEN. A rule setting `display: none` under the tier attribute
 * would spend a property no state channel names, and the component already holds the tier: it is what computed
 * the line count.
 *
 * ITS CONTENT SITS IN ONE BLOCK CHILD, because a button centres its content and a calendar block's title is
 * top-aligned. `block.css` carries the measurement that found it. */

import { useEffect, useRef, type CSSProperties, type PointerEvent } from "react";

import { GlyphSlot } from "../marks";
import { blockPaint } from "./blockPaint";
import { tierDrawsTitle, tierFor, titleLineCount } from "./tiers";
import type { Box } from "./geometry";
import type { Placement } from "./overlap";
import type { GridBlock } from "./types";
import "../../primitives/states.css";
import "./block.css";

/** Where a block sits: the box the axis gives it, and the column share overlap gives it. */
export interface BlockPlacement extends Box {
  readonly across: Placement;
}

/**
 * The states a block can be in, all of which arrive from whatever owns selection and authority.
 *
 * Absent means at rest, so a read-only render passes none of them and a block still draws every channel it owns
 * at its resting value.
 */
export interface BlockStates {
  readonly isSelected?: boolean | undefined;
  readonly isConflicted?: boolean | undefined;
  readonly isProposalTarget?: boolean | undefined;
  readonly isProposalSource?: boolean | undefined;
}

export interface BlockProps {
  readonly block: GridBlock;
  readonly placement: BlockPlacement;
  readonly states?: BlockStates | undefined;
  /** Selecting is the reader's, so it arrives from whatever owns selection. */
  readonly onSelect?: (() => void) | undefined;
  /** A drag begins here, and the pointer position is what the grid turns into a quarter hour. */
  readonly onPointerDown?: ((event: PointerEvent<HTMLButtonElement>) => void) | undefined;
}

/** A style object carrying the two values that are per-block rather than per-class. */
interface BlockStyle extends CSSProperties {
  readonly "--lines"?: number;
}

const PLACES = 3;

/* A stable empty reading, so a block at rest does not take a fresh object on every render. */
const AT_REST: BlockStates = {};

export function Block({ block, placement, states = AT_REST, onSelect, onPointerDown }: BlockProps) {
  const tier = tierFor(placement.heightPx);
  const lines = titleLineCount(placement.heightPx);
  const isAnchor = block.origin === "anchor";
  const self = useRef<HTMLButtonElement>(null);

  /* SELECTION MOVES FOCUS, which is what makes the keyboard reach every block at every tier: `j` and `k` do not care
   * how tall a block is, and a sliver-tier block gets the focus ring the kit already assigns rather than a second
   * cursor invented for the grid. Focusing here rather than from the grid keeps it one statement per block. */
  useEffect(() => {
    if (states.isSelected === true && self.current !== null) self.current.focus();
  }, [states.isSelected]);

  const style: BlockStyle = {
    top: `${placement.topPx.toFixed(PLACES)}px`,
    height: `${placement.heightPx.toFixed(PLACES)}px`,
    left: leftEdge(placement.across),
    right: rightEdge(placement.across),
    zIndex: placement.across.layer,
    "--lines": lines,
  };

  return (
    <button
      aria-label={accessibleName(block)}
      className={blockPaint(block.pigment, "state-row")}
      data-conflict={states.isConflicted === true ? "" : undefined}
      data-origin={block.origin}
      data-pinned={block.isPinned ? "" : undefined}
      data-proposal={states.isProposalTarget === true ? "" : undefined}
      data-selected={states.isSelected === true ? "" : undefined}
      data-split={placement.across.isSplit ? "" : undefined}
      data-tier={tier}
      onClick={onSelect}
      onPointerDown={onPointerDown}
      ref={self}
      style={style}
      type="button"
    >
      {isAnchor ? <span aria-hidden="true" className="week-block__hatch" /> : null}
      <span className="week-block__body">
        <span className="week-block__glyph">
          <GlyphSlot
            isPinned={block.isPinned}
            isProposalSource={states.isProposalSource}
            origin={tierDrawsTitle(tier) ? undefined : block.origin}
            overlapCount={placement.across.overlapCount ?? undefined}
          />
        </span>
        {tierDrawsTitle(tier) ? <span className="week-block__title">{block.title}</span> : null}
      </span>
    </button>
  );
}

/**
 * What a reader hears, which is the whole title and the Area it is charged to.
 *
 * Composed at every tier, because the tier ladder degrades what is DRAWN and a name is not drawn.
 */
function accessibleName(block: GridBlock): string {
  return block.areaName === null ? block.title : `${block.title} · ${block.areaName}`;
}

/* THE INSET IS ADDED TO THE COLUMN SHARE RATHER THAN REPLACED BY IT, so a block's own rules stay off the column
 * divider at every overlap depth. An earlier rendering dropped the inset the moment a column split, which put the
 * leftmost block's bottom rule on top of the divider it was supposed to sit beside. */
function leftEdge(across: Placement): string {
  if (across.indentSteps > 0) {
    return `calc(var(--grid-inset) + ${across.indentSteps} * var(--overlap-indent))`;
  }
  return `calc(var(--grid-inset) + ${(across.left * 100).toFixed(PLACES)}%)`;
}

function rightEdge(across: Placement): string {
  return `calc(var(--grid-inset) + ${(across.right * 100).toFixed(PLACES)}%)`;
}
