/* THE LAYOUT LAYER: containers and structure, and nothing that knows what a Block or an Area is.
 *
 * It may import `primitives` and itself, and nothing above it. `scripts/check-imports` resolves every import
 * here against the filesystem and refuses one that lands in `ui/domain`, `api/`, `contract/`, `routes/` or
 * `app/`, and oxlint refuses the same by specifier. A container that needs to name a `Notice` is a domain
 * component, not an under-permitted layout one.
 *
 * WHAT EACH COMPONENT OWNS, since the layer is small enough to state:
 *
 *   Pane      a column, its rhythm, and the min-width that stops a dense child widening it
 *   Strip     a horizontal band, at the reserved height or the automatic one
 *   StatCell  a figure in mono with tabular digits, and never in the serif
 *   Panel     the bordered block, and the ink header that is one of the product's two ink fills
 *   Card      one figure with a footer, which is a Panel around a StatCell
 *   Rule      the hairline, drawn in the ink the surface it lands on calls for
 *   Gutter    the adornment column at the head of a row, reserved whether or not it is filled
 *   FormRow   a label, a field, and one message, with the ids that tie the three together
 *
 * NO COMPONENT HERE TAKES A `className`. Variation is a variant, which is a named design decision; a
 * `className` would let a screen paste a utility into a container the design language has already settled.
 *
 * NO COMPONENT HERE DRAWS A STATE. Every state channel in the kit is assigned in `ui/primitives/states.css`,
 * and a container that hovered or highlighted would be assigning one a second time. `check-channels` refuses
 * it, and `__tests__/layerRules.test.ts` asserts the layer spends no state at all. */

export { Card, type CardProps } from "./Card";
export { FormRow, type FormRowField, type FormRowGroupField, type FormRowProps } from "./FormRow";
export { Gutter, type GutterProps } from "./Gutter";
export { Pane, type PaneProps } from "./Pane";
export { Panel, type PanelProps } from "./Panel";
export { Rule, type RuleProps } from "./Rule";
export { StatCell, type StatCellProps } from "./StatCell";
export { Strip, type StripProps } from "./Strip";
