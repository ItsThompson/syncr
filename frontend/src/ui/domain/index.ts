/* THE DOMAIN LAYER: everything in the kit that knows what a Block, an Area or a Notice is.
 *
 * It may import `layout`, `primitives` and itself, plus `contract` for the types it renders, and nothing above
 * that. `scripts/check-imports` resolves every import here against the filesystem and refuses one that lands in
 * `api/`, `routes/` or `app/`, and oxlint refuses the same by specifier.
 *
 * IMPORTING ONE COMPONENT LOADS EVERY FAMILY'S STYLESHEET, and that is accepted rather than overlooked. Each
 * family imports its own sheet for the side effect and this barrel re-exports all of them, so a screen that
 * takes `Table` from here is served the whole layer's CSS. Every family below is rendered by at least one
 * route, so none of it is bytes a session never uses. The alternative is a barrel with no side effects, which
 * costs a second import convention across the kit -- a component from one path, its stylesheet from another --
 * for `scripts/check-imports` and oxlint to police, and it breaks the property both of them hold: that
 * `ui/domain` is one thing. What the side effect costs is a figure rather than a sentence: `npm run
 * lint:bundle` builds one import through this barrel and one from the component's own module, and prints the
 * difference.
 *
 * WHAT EACH FAMILY OWNS:
 *
 *   shell     the top bar, the paper sidebar, the keyboard map, the command palette and the help overlay
 *   marks     the small marks a row carries: an Area chip, a key hint, and the block glyph slot
 *   charts    the five charts, the Area legend, and the two bounded-progress forms
 *   notices   the three volumes, which are position, and the four pigments, which are kind
 *   status    the three surfaces with nothing to show, none of which spins
 *   table     an --h-row pitch a long cell grows past, declared column widths, tabular figures, a sortable header
 *   ledger    the Today register's row, with the outcome controls arriving as children
 *   wizard    first run's numbered steps, with a caret on the current one and no progress bar
 *   plate     the dithered illustration plates, which are never behind data
 *   week-grid the seven-column proportional grid: geometry, the tier ladder, overlap, the bands and the strip
 *   verdict-panel  the week's feasibility at panel volume: the lead sentence, the concessions, the gaps, the offers
 *   session   the weekly session's raised items, at panel volume in amber and in that mode only
 *   reason-rows    the labelled-row set a reason record and a definition list are both drawn as
 *
 * The week grid renders `WeekDay`s and knows nothing about a response: turning one into the other is the route's
 * business, because `contract` is the only directory above this layer a component may read. */

export * from "./charts";
export * from "./ledger";
export * from "./marks";
export * from "./notices";
export * from "./plate";
export * from "./reason-rows";
export * from "./session";
export * from "./shell";
export * from "./status";
export * from "./table";
export * from "./verdict-panel";
export * from "./week-grid";
export * from "./wizard";
