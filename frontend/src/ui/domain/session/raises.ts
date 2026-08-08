/* WHAT THE WEEKLY SESSION RAISES, as the kit renders it.
 *
 * The kit does not know what a response is, so a raise arrives here already resolved: the api's own sentence has
 * become `statement`, and its `weeks` count has become the text beside it or nothing. The route does that narrowing,
 * which is the same boundary `PanelVerdict` sits on.
 *
 * `kind` IS OPEN TEXT HERE, DELIBERATELY. The panel groups by it and renders it as an eyebrow; which kinds exist is the
 * api's vocabulary, and a closed union in the kit would have to be extended in two packages every time a category is
 * added. What the kit owns is the ORDER the groups draw in, which is the order the route hands them. */

/** One thing the session raises: what it is about, what it names, and what it says. */
export interface SessionRaise {
  /** Stable for one raised thing across two reads, so a list keys on it rather than on a position. */
  readonly key: string;
  /** Which category this is, in the api's own vocabulary. Rendered as the row's eyebrow. */
  readonly kind: string;
  /** The eyebrow the group draws, which is the kind in the reader's words. */
  readonly heading: string;
  /** The thing itself, in the words the reader knows it by. */
  readonly title: string;
  /** What to make of it. Composed server-side, so the CLI and the screen say one thing. */
  readonly statement: string;
}

/** One group of raises: the heading, and the rows under it. */
export interface RaiseGroup {
  readonly kind: string;
  readonly heading: string;
  readonly raises: readonly SessionRaise[];
}

/**
 * The raises grouped by kind, in the order they arrived.
 *
 * First appearance wins, so the caller's order is the panel's order: which category a reader meets first is a product
 * decision and it belongs with the payload rather than with a sort here.
 */
export function groupRaises(raises: readonly SessionRaise[]): readonly RaiseGroup[] {
  const grouped = new Map<string, SessionRaise[]>();
  const headings = new Map<string, string>();
  for (const raise of raises) {
    const held = grouped.get(raise.kind);
    if (held === undefined) {
      grouped.set(raise.kind, [raise]);
      headings.set(raise.kind, raise.heading);
    } else {
      held.push(raise);
    }
  }
  return [...grouped].map(([kind, group]) => ({
    kind,
    heading: headings.get(kind) ?? kind,
    raises: group,
  }));
}
