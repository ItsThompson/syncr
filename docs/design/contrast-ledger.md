# Contrast ledger

**Generated. Do not edit.** Produced by `npm run lint:contrast -- --write` in `frontend/`, and
regenerated in CI by `npm run lint:contrast`, which fails on any difference.

Every ink the shipped stylesheets draw with, against every surface they fill with, with the ratio
computed from `frontend/src/tokens/` on the way past. Nothing here is claimed.

A cell that does not clear its floor is not automatically a defect: `--on-ink` on `--paper` is
1.08:1 and could not be otherwise, because that ink exists for an ink-filled surface. What a cell
with no ratio would be is a pair nobody has measured, and the audit refuses one.

| Floor | Applies to |
|---|---|
| 4.5:1 | text, at every size this product sets |
| 3.0:1 | an indicator: a border, a rule, a dot, a glyph |

The floor shown per row is the strictest one any shipped declaration puts that ink to, classified by
the property that writes it: a label's floor is 4.5:1 and a border's is 3:1, and a `color` on a rule
that also paints a hatch is a carrier for the hatch's own `currentColor` rather than text. A GLYPH is
a mark and its own floor is 3:1, which no property can tell from a label: an ink used only on a mark
is therefore shown against the stricter floor here, and the structural rule that no prose may take a
signal pigment is asserted in `frontend/src/ui/domain/__tests__/pigment.test.ts` instead.

## The matrix

| ink | floor | `--amber-wash` | `--area-01` | `--area-02` | `--area-03` | `--area-04` | `--area-05` | `--area-06` | `--area-07` | `--area-08` | `--area-09` | `--area-10` | `--area-11` | `--area-12` | `--frame-wash` | `--ink` | `--ink-deep` | `--ink-wash` | `--paper` | `--paper-raised` | `--rule` | `--state-hover` | `--unallocated` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `--forbidden-hatch-ink` | 3.0:1 | 1.40 ✗ | 3.14 | 3.15 | 3.12 | 3.17 | 3.15 | 3.14 | 3.15 | 3.14 | 3.15 | 3.15 | 3.13 | 3.15 | 1.52 ✗ | 6.71 | 8.65 | 1.48 ✗ | 1.59 ✗ | 1.71 ✗ | 1.00 ✗ | 1.48 ✗ | 3.08 |
| `--grid-line-quarter-drag` | 3.0:1 | 1.40 ✗ | 3.14 | 3.15 | 3.12 | 3.17 | 3.15 | 3.14 | 3.15 | 3.14 | 3.15 | 3.15 | 3.13 | 3.15 | 1.52 ✗ | 6.71 | 8.65 | 1.48 ✗ | 1.59 ✗ | 1.71 ✗ | 1.00 ✗ | 1.48 ✗ | 3.08 |
| `--ink` | 4.5:1 | 9.39 | 2.14 ✗ | 2.13 ✗ | 2.15 ✗ | 2.12 ✗ | 2.13 ✗ | 2.14 ✗ | 2.13 ✗ | 2.13 ✗ | 2.13 ✗ | 2.13 ✗ | 2.14 ✗ | 2.13 ✗ | 10.17 | 1.00 ✗ | 1.29 ✗ | 9.91 | 10.65 | 11.50 | 6.71 | 9.91 | 2.18 ✗ |
| `--ink-bright` | 4.5:1 | 7.53 | 1.71 ✗ | 1.71 ✗ | 1.72 ✗ | 1.70 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.72 ✗ | 1.71 ✗ | 8.16 | 1.25 ✗ | 1.61 ✗ | 7.94 | 8.53 | 9.22 | 5.38 | 7.94 | 1.75 ✗ |
| `--ink-deep` | 4.5:1 | 12.11 | 2.76 ✗ | 2.74 ✗ | 2.77 ✗ | 2.73 ✗ | 2.75 ✗ | 2.75 ✗ | 2.74 ✗ | 2.75 ✗ | 2.75 ✗ | 2.75 ✗ | 2.76 ✗ | 2.74 ✗ | 13.12 | 1.29 ✗ | 1.00 ✗ | 12.78 | 13.73 | 14.83 | 8.65 | 12.78 | 2.81 ✗ |
| `--ink-soft` | 4.5:1 | 6.98 | 1.59 ✗ | 1.58 ✗ | 1.60 ✗ | 1.57 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 7.56 | 1.35 ✗ | 1.74 ✗ | 7.36 | 7.91 | 8.55 | 4.99 | 7.36 | 1.62 ✗ |
| `--on-ink` | 4.5:1 | 1.22 ✗ | 5.38 | 5.40 | 5.35 | 5.43 | 5.39 | 5.39 | 5.41 | 5.39 | 5.40 | 5.40 | 5.36 | 5.40 | 1.13 ✗ | 11.50 | 14.83 | 1.16 ✗ | 1.08 ✗ | 1.00 ✗ | 1.71 ✗ | 1.16 ✗ | 5.28 |
| `--oxide-ink` | 4.5:1 | 7.31 | 1.66 ✗ | 1.66 ✗ | 1.67 ✗ | 1.65 ✗ | 1.66 ✗ | 1.66 ✗ | 1.66 ✗ | 1.66 ✗ | 1.66 ✗ | 1.66 ✗ | 1.67 ✗ | 1.66 ✗ | 7.92 | 1.28 ✗ | 1.66 ✗ | 7.71 | 8.29 | 8.95 | 5.22 | 7.71 | 1.70 ✗ |
| `--paper-raised` | 3.0:1 | 1.22 ✗ | 5.38 | 5.40 | 5.35 | 5.43 | 5.39 | 5.39 | 5.41 | 5.39 | 5.40 | 5.40 | 5.36 | 5.40 | 1.13 ✗ | 11.50 | 14.83 | 1.16 ✗ | 1.08 ✗ | 1.00 ✗ | 1.71 ✗ | 1.16 ✗ | 5.28 |
| `--rule` | 4.5:1 | 1.40 ✗ | 3.14 ✗ | 3.15 ✗ | 3.12 ✗ | 3.17 ✗ | 3.15 ✗ | 3.14 ✗ | 3.15 ✗ | 3.14 ✗ | 3.15 ✗ | 3.15 ✗ | 3.13 ✗ | 3.15 ✗ | 1.52 ✗ | 6.71 | 8.65 | 1.48 ✗ | 1.59 ✗ | 1.71 ✗ | 1.00 ✗ | 1.48 ✗ | 3.08 ✗ |
| `--rule-control` | 3.0:1 | 4.31 | 1.02 ✗ | 1.02 ✗ | 1.01 ✗ | 1.03 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 4.67 | 2.18 ✗ | 2.81 ✗ | 4.55 | 4.89 | 5.28 | 3.08 | 4.55 | 1.00 ✗ |
| `--rule-on-ink` | 3.0:1 | 7.53 | 1.71 ✗ | 1.71 ✗ | 1.72 ✗ | 1.70 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.71 ✗ | 1.72 ✗ | 1.71 ✗ | 8.16 | 1.25 ✗ | 1.61 ✗ | 7.94 | 8.53 | 9.22 | 5.38 | 7.94 | 1.75 ✗ |
| `--signal-amber` | 4.5:1 | 3.69 ✗ | 1.19 ✗ | 1.20 ✗ | 1.18 ✗ | 1.20 ✗ | 1.19 ✗ | 1.19 ✗ | 1.20 ✗ | 1.19 ✗ | 1.19 ✗ | 1.20 ✗ | 1.19 ✗ | 1.20 ✗ | 4.00 ✗ | 2.54 ✗ | 3.28 ✗ | 3.89 ✗ | 4.18 ✗ | 4.52 | 2.64 ✗ | 3.89 ✗ | 1.17 ✗ |
| `--signal-oxide` | 4.5:1 | 5.40 | 1.23 ✗ | 1.22 ✗ | 1.24 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.22 ✗ | 5.85 | 1.74 ✗ | 2.24 ✗ | 5.70 | 6.12 | 6.61 | 3.86 ✗ | 5.70 | 1.25 ✗ |
| `--signal-verdigris` | 4.5:1 | 5.02 | 1.14 ✗ | 1.14 ✗ | 1.15 ✗ | 1.13 ✗ | 1.14 ✗ | 1.14 ✗ | 1.14 ✗ | 1.14 ✗ | 1.14 ✗ | 1.14 ✗ | 1.15 ✗ | 1.14 ✗ | 5.44 | 1.87 ✗ | 2.41 ✗ | 5.29 | 5.69 | 6.15 | 3.59 ✗ | 5.29 | 1.16 ✗ |
| `--state-conflict-color` | 3.0:1 | 5.40 | 1.23 ✗ | 1.22 ✗ | 1.24 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.22 ✗ | 5.85 | 1.74 ✗ | 2.24 ✗ | 5.70 | 6.12 | 6.61 | 3.86 | 5.70 | 1.25 ✗ |
| `--state-overdue-color` | 3.0:1 | 5.40 | 1.23 ✗ | 1.22 ✗ | 1.24 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.23 ✗ | 1.22 ✗ | 1.23 ✗ | 1.22 ✗ | 5.85 | 1.74 ✗ | 2.24 ✗ | 5.70 | 6.12 | 6.61 | 3.86 | 5.70 | 1.25 ✗ |
| `--state-selected-color` | 3.0:1 | 12.11 | 2.76 ✗ | 2.74 ✗ | 2.77 ✗ | 2.73 ✗ | 2.75 ✗ | 2.75 ✗ | 2.74 ✗ | 2.75 ✗ | 2.75 ✗ | 2.75 ✗ | 2.76 ✗ | 2.74 ✗ | 13.12 | 1.29 ✗ | 1.00 ✗ | 12.78 | 13.73 | 14.83 | 8.65 | 12.78 | 2.81 ✗ |
| `--text` | 4.5:1 | 9.39 | 2.14 ✗ | 2.13 ✗ | 2.15 ✗ | 2.12 ✗ | 2.13 ✗ | 2.14 ✗ | 2.13 ✗ | 2.13 ✗ | 2.13 ✗ | 2.13 ✗ | 2.14 ✗ | 2.13 ✗ | 10.17 | 1.00 ✗ | 1.29 ✗ | 9.91 | 10.65 | 11.50 | 6.71 | 9.91 | 2.18 ✗ |
| `--text-muted` | 4.5:1 | 4.31 ✗ | 1.02 ✗ | 1.02 ✗ | 1.01 ✗ | 1.03 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 1.02 ✗ | 4.67 | 2.18 ✗ | 2.81 ✗ | 4.55 | 4.89 | 5.28 | 3.08 ✗ | 4.55 | 1.00 ✗ |
| `--text-on-wash` | 4.5:1 | 6.98 | 1.59 ✗ | 1.58 ✗ | 1.60 ✗ | 1.57 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 1.58 ✗ | 1.59 ✗ | 1.58 ✗ | 7.56 | 1.35 ✗ | 1.74 ✗ | 7.36 | 7.91 | 8.55 | 4.99 | 7.36 | 1.62 ✗ |
| `--verdigris-ink` | 4.5:1 | 7.15 | 1.63 ✗ | 1.62 ✗ | 1.64 ✗ | 1.61 ✗ | 1.62 ✗ | 1.63 ✗ | 1.62 ✗ | 1.62 ✗ | 1.62 ✗ | 1.62 ✗ | 1.63 ✗ | 1.62 ✗ | 7.74 | 1.31 ✗ | 1.69 ✗ | 7.54 | 8.10 | 8.75 | 5.11 | 7.54 | 1.66 ✗ |

484 pair(s) measured, 22 ink(s) against 22 surface(s). 313 do not clear the ink's floor and are marked ✗, which means the pairing must not be composed rather than that a token is wrong.

## What lands on an ink-filled surface

`--ink` and `--ink-deep` are the fills that are ink rather than paper, and an ink chosen to be
read on paper is not readable on either. Every ink the product writes as text is measured against both
here, so the pairing is on record whether or not anything composes it.

| ink | `--ink` | `--ink-deep` |
|---|---|---|
| `--ink` | 1.00 | 1.29 |
| `--ink-bright` | 1.25 | 1.61 |
| `--ink-deep` | 1.29 | 1.00 |
| `--ink-soft` | 1.35 | 1.74 |
| `--on-ink` | 11.50 | 14.83 |
| `--oxide-ink` | 1.28 | 1.66 |
| `--rule` | 6.71 | 8.65 |
| `--signal-amber` | 2.54 | 3.28 |
| `--signal-oxide` | 1.74 | 2.24 |
| `--signal-verdigris` | 1.87 | 2.41 |
| `--text` | 1.00 | 1.29 |
| `--text-muted` | 2.18 | 2.81 |
| `--text-on-wash` | 1.35 | 1.74 |
| `--verdigris-ink` | 1.31 | 1.69 |

14 ink(s) written as text, against 2 ink-filled surface(s): 28 pairing(s) measured.

### The pairings a rule states

A rule that declares its own fill and its own ink names both halves of a pairing in one place, which no
DOM is needed to read. Those are the pairings held to the text floor on an ink fill; the rest of the
table above is recorded and not enforced, because nothing says a class reaches that surface.

| rule | ink | fill | ratio |
|---|---|---|---|
| `ui/layout/Panel.css .panel__header { color }` | `--on-ink` | `--ink-deep` | 14.83 |
| `ui/primitives/Button.css .button { color }` | `--on-ink` | `--ink` | 11.50 |
| `ui/primitives/Calendar.css .calendar__day[aria-selected="true"] { color }` | `--on-ink` | `--ink-deep` | 14.83 |
| `ui/primitives/Dialog.css .dialog__header { color }` | `--on-ink` | `--ink-deep` | 14.83 |

4 pairing(s) stated on an ink-filled surface, of 25 stated on any surface, held to 4.5:1.

## Which declaration set each floor

An ink used both as a label and as a border is held to the label's floor, so the row's floor is the
strictest shipped use. This names that use, because the classification is checkable rather than
something to take on trust: a `color` on a rule that also paints a hatch is a carrier for the
hatch's own `currentColor` rather than text, and is held to the indicator floor for that reason.

| ink | floor | set by |
|---|---|---|
| `--forbidden-hatch-ink` | 3.0:1 | `ui/domain/week-grid/band.css .week-band { color }` |
| `--grid-line-quarter-drag` | 3.0:1 | `ui/domain/week-grid/grid.css [data-dragging] .week-grid__line--quarter { border-top-color }` |
| `--ink` | 4.5:1 | `ui/domain/charts/charts.css .deviation__name { color }` |
| `--ink-bright` | 4.5:1 | `ui/domain/notices/notices.css .notice--info .notice__mark { color }` |
| `--ink-deep` | 4.5:1 | `ui/domain/charts/charts.css .legend__name { color }` |
| `--ink-soft` | 4.5:1 | `ui/domain/status/status.css .status__detail { color }` |
| `--on-ink` | 4.5:1 | `ui/domain/marks/marks.css .key-hint { color }` |
| `--oxide-ink` | 4.5:1 | `ui/domain/notices/notices.css .notice--oxide .notice__title { color }` |
| `--paper-raised` | 3.0:1 | `ui/domain/charts/charts.css .pie__wedge { stroke }` |
| `--rule` | 4.5:1 | `ui/domain/charts/charts.css .meter__cell--empty { color }` |
| `--rule-control` | 3.0:1 | `ui/primitives/Button.css .button--secondary { border-color }` |
| `--rule-on-ink` | 3.0:1 | `ui/layout/Rule.css .on-ink-surface .rule { border-top-color }` |
| `--signal-amber` | 4.5:1 | `ui/domain/notices/notices.css .notice--amber .notice__mark { color }` |
| `--signal-oxide` | 4.5:1 | `ui/domain/notices/notices.css .notice--oxide .notice__mark { color }` |
| `--signal-verdigris` | 4.5:1 | `ui/domain/notices/notices.css .notice--verdigris .notice__mark { color }` |
| `--state-conflict-color` | 3.0:1 | `ui/domain/week-grid/block.css .week-block[data-conflict] { border-left-color }` |
| `--state-overdue-color` | 3.0:1 | `ui/primitives/states.css .state-row[data-overdue] { border-left-color }` |
| `--state-selected-color` | 3.0:1 | `ui/domain/week-grid/block.css .week-block[data-selected] { border-left-color }` |
| `--text` | 4.5:1 | `base.css body { color }` |
| `--text-muted` | 4.5:1 | `ui/domain/charts/charts.css .chart__caption { color }` |
| `--text-on-wash` | 4.5:1 | `ui/domain/verdict-panel/verdict.css .verdict-panel { color }` |
| `--verdigris-ink` | 4.5:1 | `ui/domain/notices/notices.css .notice--verdigris .notice__title { color }` |

## What no ratio can describe

Four shapes are not a flat colour and are recorded rather than measured, because a ratio computed
for one of them would be a made-up figure. A hatch's own ink is measured where its mix percentage
is known, in `frontend/src/ui/domain/charts/__tests__/contrast.test.ts`.

| where | value | why |
|---|---|---|
| `--hatch-ink` | `currentColor` | currentColor takes whatever colour it inherits |
| `--scrim` | `color-mix(in srgb, var(--ink-deep) 30%, transparent)` | it carries transparency, so what shows through is the content under it |
| `ui/domain/charts/charts.css .chart-ink` | `color-mix(in srgb, var(--ai) var(--hatch-mix), var(--paper-raised))` | it is a mix, measured where its percentage is known, in the charts' own contrast ledger |

## What the palette was read from

- `frontend/src/base.css`
- `frontend/src/theme.css`
- `frontend/src/ui/domain/charts/charts.css`
- `frontend/src/ui/domain/ledger/ledger.css`
- `frontend/src/ui/domain/marks/marks.css`
- `frontend/src/ui/domain/notices/notices.css`
- `frontend/src/ui/domain/plate/plate.css`
- `frontend/src/ui/domain/reason-rows/rows.css`
- `frontend/src/ui/domain/reason-rows/tokens.css`
- `frontend/src/ui/domain/shell/help.css`
- `frontend/src/ui/domain/shell/palette.css`
- `frontend/src/ui/domain/status/status.css`
- `frontend/src/ui/domain/table/table.css`
- `frontend/src/ui/domain/verdict-panel/tokens.css`
- `frontend/src/ui/domain/verdict-panel/verdict.css`
- `frontend/src/ui/domain/week-grid/band.css`
- `frontend/src/ui/domain/week-grid/block.css`
- `frontend/src/ui/domain/week-grid/grid.css`
- `frontend/src/ui/domain/week-grid/strip.css`
- `frontend/src/ui/domain/week-grid/tokens.css`
- `frontend/src/ui/domain/wizard/wizard.css`
- `frontend/src/ui/layout/FormRow.css`
- `frontend/src/ui/layout/Gutter.css`
- `frontend/src/ui/layout/Panel.css`
- `frontend/src/ui/layout/Rule.css`
- `frontend/src/ui/layout/StatCell.css`
- `frontend/src/ui/layout/Strip.css`
- `frontend/src/ui/primitives/Accordion.css`
- `frontend/src/ui/primitives/Button.css`
- `frontend/src/ui/primitives/Calendar.css`
- `frontend/src/ui/primitives/Command.css`
- `frontend/src/ui/primitives/DatePicker.css`
- `frontend/src/ui/primitives/Dialog.css`
- `frontend/src/ui/primitives/Icon.css`
- `frontend/src/ui/primitives/NumberStepper.css`
- `frontend/src/ui/primitives/Select.css`
- `frontend/src/ui/primitives/Tabs.css`
- `frontend/src/ui/primitives/control.css`
- `frontend/src/ui/primitives/glyphs.css`
- `frontend/src/ui/primitives/overlay.css`
- `frontend/src/ui/primitives/states.css`
- `frontend/src/ui/primitives/toggle.css`
