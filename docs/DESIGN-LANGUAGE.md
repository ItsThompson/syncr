# Design Language

syncr is a scheduling and life-management system that owns the plan. It converts long-term time allocations and a short-term task backlog into a timeblocked week, projects that week to a calendar, and adapts as reality diverges without rearranging anything behind the user's back.

The design language follows from three facts about that job.

The product's primary surface is a **seven-column proportional grid holding roughly ninety blocks a week**, read at a glance and edited by direct manipulation. The reader has to answer three questions from one rectangle: what is this, whose time is it, and may it move. That density is the whole design problem.

The product's most valuable output is sometimes **a refusal**. When a week cannot hold its commitments, syncr says so, quantifies the shortfall, and enumerates the tradeoffs without choosing. A refusal has to read as authoritative and calm rather than as an error.

And **every placement has to explain itself**. The scheduler is deterministic and no language model sits in the placement loop, so an explanation is a projection of computed values rather than generated prose. That constraint shapes a component.

The aesthetic is inherited, unchanged, from a sibling product: cobalt ink on cream paper, hairline rules, square corners, no blur, uppercase tracked micro-labels, monospace everywhere, and a single classical serif used twice. What syncr adds is a sealed twelve-pigment ramp for Areas, a proportional grid with a four-step label ladder, and a stricter motion policy.

## Principles

**One ink, with one sealed exception.** The system is drawn in a single cobalt hue at seven steps. Body text is not a separate color from the accent. The exception is the Area ramp, and it is sealed rather than open: see [Color](#color).

**Color is not a channel you can spend freely.** A wash has roughly 1.1:1 contrast against paper, which is the entire dynamic range a tint has on cream. So a wash never carries meaning alone. It always pairs with a rule, a glyph, or a border.

**Density is the point.** Controls are 26px, table rows are 28px, body text is 12px, and a block title is 11.5px. Off-the-shelf component defaults are built for touch and run roughly 40% taller. Every one of them gets overridden.

**The axis never lies.** A block's height is proportional to its duration at every zoom level. When a block is too short to hold its own title, the block degrades and the axis does not.

**Every number is computed, never asserted.** The reference sheets compute their own contrast ledgers, character budgets, tier arithmetic and failure counts from the linked tokens at load. Prose drifts; arithmetic does not. Where a figure is constructed rather than measured, the sheet says so at the point it appears.

**Ornament stays out of the working surfaces.** Illustration belongs in headers, empty states, and dead space. It never appears behind the week grid, a table, or a chart.

## Color

Tokens live in `frontend/src/tokens/color.css`. Read that file for values; this section covers the rules.

Cobalt carries four semantic roles. `--ink` is body text, block titles and table data. `--ink-deep` is labels, page titles and the selected-block rule. `--ink-bright` is the focus ring, status dots, links and the now rule. `--ink-soft` is secondary prose, which in practice means reasons and explanations.

**The focus ring is chosen by the surface it lands on, not by the element's own fill.** The ring is drawn at a 2px offset, so it sits on the parent surface. A primary button has an ink fill but a paper parent, and inverting its ring would give `--paper-raised` on `--paper` at 1.08:1. So scope the inverse ring to the container whose fill the ring will actually touch:

```css
.dialog > header :focus-visible { outline: var(--state-focus-ring-inverse) }
```

syncr has exactly one such surface: an ink-filled dialog or panel header. **The sidebar is paper.** That is a deliberate departure from the inherited language, which fills its sidebar with `--ink-deep`. Rendered on a screen whose whole point is a calm grid, an ink sidebar dominated, and it spent the loudest treatment in the system on the most permanently visible surface. The current nav item instead takes `--ink-wash` plus a 3px `--ink-deep` left rule, which is the same channel a selected block uses. One idea, one form.

The signal pigments are oxide, verdigris and amber, sealed to status and severity indicators: dots, rules, glyphs and their labels. Never a fill, never a heading, never in navigation, never a pill.

**Each signal names two steps, and they are not interchangeable.** The marker step carries dots, rules, glyphs and washes, where 3:1 is the bar. The text step carries label ink, where 4.5:1 is the bar and the marker step fails. Amber has no text step: its marker passes at 4.52:1 on a raised surface and fails at 4.18:1 on paper, so amber text appears only on raised surfaces and an amber indicator pairs with `--text-muted` text rather than coloring its own label.

Two findings from the inherited language are rules here rather than preferences. **A control border is an indicator, not decoration**: it is the only thing marking where an input begins, so it must clear 3:1, and `--rule-strong` measures 2.65:1 there and is banned on controls. Use `--rule-control`. **Syntax and code sit on `--paper-raised`, never on `--paper`**, because `--signal-amber` measures 4.52:1 on raised and fails at 4.18:1 on paper.

### The Area ramp

Areas do triple duty in this product: the wedge of the allocation model, the type of a template slot, and the category of a task. A user carries several at once and must read "which Area" pre-attentively across a week of roughly ninety blocks. Label text alone cannot do that at the fifteen-minute tier, and a tint ramp cannot either, because the entire wash channel is 1.1:1 wide.

So there are twelve Area pigments, and they are the single break with one ink. The break is sealed the same way the inherited language seals its one signal fill: a named exception with an explicit carrier list, not a general licence to reach for color.

**Legal carriers, exhaustively. One carrier per context, never two at once:**

| Context | Carrier |
|---|---|
| Proportional surfaces (the week grid) | the block's 2px top rule, and nothing else |
| Ledger surfaces (Today, Backlog, Templates, budget tables) | a filled circular chip up to 10px in the row gutter |
| Charts | a pie wedge fill or a stacked bar fill |

**Illegal everywhere:** as text, as a block or row fill, as a control border, in navigation, on a heading, on a time-series line, and as the only encoding of anything.

**A chart row is a chart context end to end.** The deviation bars are the case that forced this ruling: the row has a label cell and a bar, and a first draft put a chip in the label cell on the reasoning that a label cell is a ledger gutter. It is not. A chip beside a cobalt bar implies the bar could have been Area-colored, which muddies the one rule that component exists to demonstrate. The Area name identifies the row, which is what a name is for.

Four consequences worth stating explicitly.

**The ramp is deliberately equalized.** All twelve pigments measure within 0.1 of 5.0:1 against page paper. An earlier draft ran from 4.42:1 to 7.25:1, and the violet group read as holding more time than the moss group at equal wedge area. An uneven ramp biases the exact chart the pie review exists to show.

**Three pigments sit on the sealed signal hues by construction.** `--area-01` is near oxide, `--area-03` near amber, `--area-06` near verdigris. Squeezing twelve pigments into the remaining 270 degrees would put the hue steps below the point where dark colors separate, so the collision is accepted and the carrier rule disambiguates it: a signal is never a fill, an Area is only ever a fill or a rule.

**Pigments are assigned, not picked.** There is no color picker, because one would end the design language on the first day. Assignment order is chosen so that a user with four Areas gets four pigments roughly ninety degrees apart, and the tight yellow-brown neighbors are dealt ninth and tenth.

**Color is never the only encoding.** Roughly one man in twelve cannot separate twelve categorical hues. So every wedge and bar pairs its ink with a hatch, and every chip pairs with the Area's name. Hatch is always on and is not an accessibility toggle. Each hatch is drawn in a lighter step of the wedge's own ink so it reads as texture rather than as a second color.

**The circadian frame is outside the ramp.** Routines are not budgeted as discretionary time, so the frame takes `--frame-wash` and no Area ink. It reads as structure, not as a category competing with Fitness.

Hatch itself is a texture primitive with exactly three uses: Area redundancy on a wedge or bar, an external anchor's fill in `--rule`, and a forbidden window in `--rule`.

## Type

One family carries the whole product: JetBrains Mono. The serif, Playfair Display, appears in exactly two places: the wordmark, and the seven page titles. Not headline numbers, which stay mono, and not a mode header, because a mode is not a destination.

**The wordmark is lowercase, and that is a named exception.** Everywhere else only uppercase text is tracked out, and the inherited wordmark is uppercase tracked serif. The product's name is lowercase by design and setting it as `SYNCR` misreads it. So the wordmark is lowercase serif at zero tracking, and it is the one lowercase serif in the system. Nothing else may claim the exception.

The scale is in `frontend/src/tokens/type.css`. Each step exists because a surface needed it, and adding a step requires naming the surface that needs it.

### The block title, and the ladder it forced

A block's title is `--fs-chrome` 11.5px at `--lh-block` 1.2. That choice sets a floor, and the floor sets the zoom range, so the arithmetic is load-bearing:

```
label tier                          compact tier
 2   the Area top rule               2   the Area top rule
 2   --block-pad-t                   0   no top padding: there is no room
13.8 --fs-block at --lh-block        9.5 --fs-block-compact at --lh-block-compact
 1   the bottom rule                 1   the bottom rule
----                                ----
18.8 inside a 19px floor            12.5 inside a 13px floor
```

Four tiers, and the block degrades rather than the axis lying:

| Height | Tier | What is drawn |
|---|---|---|
| ≥ 19px | label | title at 11.5px, wrapping to as many lines as fit |
| ≥ 13px | compact | title at 9.5px, one line, no top padding |
| ≥ 8px | sliver | no title. the origin glyph and the Area top rule |
| < 8px | hairline | a bounded sliver. Area top rule only |

**The compact tier exists because a three-tier ladder was rejected in review.** A first draft went straight from title to glyph at 19px, on the reasoning that the blocks that fall through are the circadian frame and are read from position. Rendered, an unlabeled `Wake Up` reads as a rendering fault rather than as a deliberate tier. The compact tier keeps a title down to 12.5px, which covers a fifteen-minute block at the twelve-hour default on the smallest supported display.

**The hairline tier is unreachable on any supported display**, given the zoom clamp below. It is kept as a defensive floor, not as a state a user will meet.

**The title wraps to whatever fits; it does not truncate at one line.** A first draft set `white-space: nowrap`, and a measured ledger over one real week found 4 of 37 distinct titles becoming ambiguous under end-ellipsis: `Amazon Interview Prep` and `Amazon Interview Prep · Behavioral` both collapse to `Amazon Interview P…`, as do `Visual Computing Lab` and `Visual Computing Lecture`. End-ellipsis discards precisely the tail that distinguishes a title from its sibling. Those blocks run 60 to 150 minutes and are 52 to 130px tall, so the line count is computed per block from its own height and the clip lands on a line boundary.

## The week grid

**Pixels per minute is derived, not fixed.** The user chooses how many hours are visible at once, from 6 to 24, defaulting to 12, and separately declares when their own day starts and ends. The app measures the grid's height and recomputes `--px-per-min` from the two.

**The axis always expands to contain every block in the visible week.** Day bounds set the default extent, never a crop. A block hidden by the axis is a scheduling error the user cannot see.

**The zoom range is clamped by the modal duration, not the shortest one.** Thirty minutes is the most common block length by a wide margin, so the upper end of the range is capped so that a thirty-minute block always keeps a title. The cap is derived from the grid height and `--block-h-label`, which yields 16h on a 13-inch display, 22h on a 16-inch and the full 24h on a 27-inch. A zoom level at which the most common block in the system is unreadable is not a useful zoom level, so it is not offered.

**The quarter hour is drawn at rest, because the snap is fifteen minutes and the grid should show where a block can land.** The hour alone carries `--rule`; the three quarters carry `--rule-faint`. During a drag the quarters step up to hour weight, so the snap targets sharpen at the one moment the user is aiming at them.

That distribution took two rounds. A first draft drew `--rule` at every half hour and `--rule-faint` at every quarter, while each block also drew four `--rule-strong` edges: four lines an hour, two of them at cobalt weight, and the blocks vanished into the corduroy. **The remedy was not to delete the subdivision. It was to halve the cobalt.** Same line count as the version that was rejected, half the cobalt weight, and a block down from four edges to three.

**A block draws three edges, not four.** The top rule carries the Area, the bottom rule closes the block at grid weight, the left rule is reserved for state, and there is no left or right border at all. A 1px horizontal inset keeps a block's own rules off the column divider. A split block is the one exception: it takes a left `--rule`, because nothing else would divide it from its neighbor.

**Overlap uses sweep-and-columns, with no special case for any origin.** Cluster by a running maximum end, then give each block the leftmost column whose last block has already finished. Even split up to depth 3, then stagger with the later start on top at a fixed indent plus a count marker, because an even fifth of a column leaves nothing to write in.

An earlier draft special-cased the circadian frame as a full-width backdrop that never split, so a long `Sleep` span would not halve the day it backs. It was wrong twice over: `Wake Up` is also origin `frame` yet is a genuine fifteen-minute participant, and a full-width frame block painted over whatever it overlapped and clipped that block's title. Columns need no special case, depend on no paint order, and use no magic threshold.

**A forbidden window is drawn, not omitted.** The recovery shadow an anchor casts is a hatched band with a gutter label, sitting under every block in z-order. It is deliberately not a block: no fill, no Area rule, no state, because it is the absence of a block that it exists to explain. Left as nothing, a forbidden gap and an ordinary empty gap are pixel-identical and the solver appears to decline a gap for no reason.

### Width policy

**The week grid absorbs surplus width. The sidebar and the detail panel are fixed.** Block titles in the single-line tiers cannot wrap, so the grid is the only column that cannot absorb a squeeze.

**The floor is 17 characters per day column**, and every breakpoint is derived from it rather than chosen. 17 characters is where a real title stops keeping the tail that distinguishes it from its siblings. Working backwards through `--block-pad-x`, `--grid-inset` and the 3px state rule, that needs a 132.3px day column, so a 926px grid, so a 1524px viewport with the panel open.

`--bp-wide` is therefore **1536px**, not the 1440px a first draft assumed by analogy. At exactly 1440 with the panel open a day column yields 15 characters. The ledger caught it.

Below `--bp-wide` the detail panel closes to a 26px rail rather than narrowing, because a narrower panel cannot hold a reason and a narrower grid cannot hold a title. Below `--bp-compact` the grid scrolls horizontally at `--col-min` per day with the time axis sticky, so the squeeze is explicit and navigable instead of degrading all seven columns at once.

## Interaction states

**Each state owns exactly one channel, so that combinations add instead of overwrite.**

A calendar block differs from a transcript row in one way that drives all of this: it must be a bounded object distinct from the grid's own lines, so **it spends a fill just to exist.** The fill channel therefore has three values rather than two, and they order correctly by accident of the palette.

| Meaning | Channel | Value |
|---|---|---|
| Area identity | 2px top rule | `--area-NN` |
| the block exists | fill | `--paper-raised`, lighter than the page |
| hover | fill | `--ink-wash`, darker than the page |
| proposal target | fill | **none.** dashed outline only |
| conflict | 3px left rule | `--signal-oxide` |
| selected | 3px left rule | `--ink-deep` |
| focus-visible | outline at 2px offset | `--ink-bright` |
| pinned | glyph slot | a filled mark |
| origin | glyph slot | one mark per kind, below the label tiers only |

Loudness, most to least: conflict, proposal, selected, focus, hover.

**Absence of fill is the proposal channel, and dashed was rejected for it.** A dashed border already means `disabled` on a control, and one visual carrying two meanings is what this system forbids. Absence of fill is unclaimed, unambiguous, and survives forced colors, where a fill is dropped anyway. The target keeps a dashed outline as well, so that in forced colors the missing fill stops being the only difference.

**Conflict and selected share the left rule deliberately.** They cannot co-occur meaningfully: a conflict is resolved by selecting it, at which point the detail panel states it in words. Conflict wins the pixel while it lasts.

**Four meanings are moved off the block rather than given a channel.** Reality state belongs to the Today ledger. Time relation is carried by the now rule, because immutability is not a per-block property worth a pigment. Infeasibility implication is a mode entered from the verdict strip. The reason string is the detail panel's job, on selection, never hover-only.

**Validate every new state in combination, never in isolation.** In the inherited language four plausible state systems each looked correct on a single state and produced two pixel-identical rows in a combination matrix while meaning different things. `docs/design/scratch/block-states.html` carries syncr's matrix for the same purpose.

Every state except hover survives forced-colors mode, because each pairs its fill with an outline, border or glyph. Hover does not survive, which is acceptable: it is mouse-only and nothing depends on it to operate the product. The Area ramp does not survive either, which is precisely why hatch and the Area name are structural rather than optional.

## Severity

The product must never fail silently, and it must never cry wolf. Only a conflict notifies. A proposal waits quietly.

**Severity uses two independent axes.** Pigment says what kind of thing happened. Position says how much the reader should care.

| Pigment | Kind |
|---|---|
| `--ink-bright` | informational. spends no signal pigment |
| `--signal-amber` | notice. needs attention, nothing is broken |
| `--signal-oxide` | failure. something is broken |
| `--signal-verdigris` | resolved. a confirmation, used sparingly |

Volume, expressed as position: **inline** at the block or row it concerns, **panel** at the head of the affected screen, **banner** persistently in the top bar until it clears, **blocking** as a full screen.

How the known cases land:

| Case | Volume | Pigment |
|---|---|---|
| External anchor overlaps a planned block | inline on the block, plus a banner while unresolved | oxide |
| Proposal pending | inline only, outline-only ghost, no notification | none |
| Week is infeasible | panel at the head of the week | amber |
| The user's own pins breach a floor | panel, the same one | amber |
| Chronic skip, six consecutive weeks | panel, in weekly-session mode only | amber |
| Day unconfirmed | inline on the day column header | informational |
| Google write-target token expired | banner, plus a panel on Settings | oxide |
| ICS feed unreachable or stale | panel on Settings, inline on affected days | amber |
| Calendar write reconciliation failed | banner | oxide |
| Solver returned no plan | panel | oxide |
| Parameter still collecting baseline | inline on the Learned screen | **informational, never a warning** |
| Blocking, level 4 | **deliberately unused** | |

Three of those rows carry a rule rather than a placement.

**Level 4 is deliberately unused.** syncr does not block approval of a knowingly-broken week. Infeasibility is the product's most valuable output and it is a notice, not a failure: the week is impossible, not broken. Raise, warn, and allow.

**The Google write-target expiry gets the loudest non-blocking volume** because it is the most dangerous silent failure in the product. The plan quietly stops reaching the user's phone, which deletes the one thing the write target exists for.

**"Collecting baseline" must read as a normal state.** Nothing is broken while a parameter is still collecting, and marking it in oxide would teach the user to distrust a working system.

**Actionable means naming what still works.** A degradation notice states which capability is unavailable and which remain. When the write target fails, reading anchors still works and writing does not, so the notice says exactly that.

## The verdict panel and its tradeoffs

Infeasibility is a **panel**, amber, at the head of the week. Two rules govern it.

**Its height is fixed and its rows scroll inside it.** A panel that grew and shrank as pins accumulate would shift the grid under the cursor mid-drag. That is a layout-stability rule, not a motion one.

**Each tradeoff is a button that generates a proposal, never a direct mutation.** Clicking "reduce the sleep floor by 1h" produces a plan revision with status `proposed`, which the user then approves like any other. No new mechanism, no destructive action taken from a warning panel, and the rule that syncr may never move or remove without assent holds with no exception carved out.

## The reason record

Every placement explains itself, and the explanation is **rendered from a structured record through a template catalogue, never generated prose.** The scheduler is deterministic and no language model sits in the placement loop, so a sentence that cannot be traced to a value the solver computed is worse than no sentence.

Six clause kinds, each a projection of data the solver already has to compute:

| Clause | Renders | Source |
|---|---|---|
| `blocked` | a rejected candidate window and the constraint that rejected it | the hard-constraint checker |
| `dominant` | the objective term with the largest share of total cost | the objective breakdown on the plan revision |
| `bound` | the binding source and its cursor position | the habit's binding source |
| `floor` | an Area floor that forced or forbade the placement | the floor constraint |
| `pinned` | the user's own edit, with the date it was made | the pin itself |
| `instead of` | the placement the pin overrode, and its objective delta | the superseded placement, stored with the pin |

**The clause budget is bounded**: the top two rejected windows, the dominant term, and one superseded placement. Recording every candidate for ninety blocks a week would bloat a document that lives in an append-only store forever.

Because the budget is bounded and the shape is fixed, **the panel renders labeled rows rather than a paragraph.** A paragraph implies unbounded prose; rows imply a fixed schema. This is not a stylistic preference: it is the component matching the data.

**A pinned block shows its counterfactual, which is a storage requirement rather than a display choice.** A pin's reason is otherwise just "you put it here", which is true and unhelpful. Showing what the solver would have chosen instead, and what that choice cost, turns a pin into a visible trade. It means the superseded placement and its objective delta must be persisted alongside the pin, permanently. That cost is worth paying twice over: it is also exactly the pairwise comparison the learning layer consumes, so the data would be worth keeping even if the panel never showed it.

## Derived state is read-only

A rotation cursor is the clearest case. `Gym` is on `Legs` *because* `Chest & Back` was confirmed complete, so the cursor is a projection of the append-only outcome log rather than a field. It is displayed read-only with that provenance, and there is no "set cursor" control, because editing derived state desyncs it from the log that produced it.

A wrong cursor means a wrong confirmation: the user fixes the day on Today, which already supports backfill, and the cursor re-derives. Overriding a single occurrence is a rebind, which is a pin, which is a mechanism that already exists. No new concept, and no desync possible by construction.

Prefer this shape wherever it fits. It removes a UI affordance rather than adding one.

## Motion

**Zero, without exception.** Nothing eases, fades, slides, shimmers or spins. There are no skeleton loaders, no progress bars, and no spinner. `--duration` is `0s`.

The inherited language kept one exception, because its 4.6-second cold-start index had to report progress. syncr has no such wait: a solve over roughly thirty blocks a day is instantaneous, and calendar sync reports as a count that changes when a number changes, which is a discrete redraw rather than motion.

**A drag is discrete.** Dragging a block does not move the block. A hairline insertion marker snaps to the quarter hour under the cursor, and the block redraws once, on drop. Reflow of the unpinned remainder is one redraw, never an animated settle. Continuous input, discrete output.

**Instant collapse is a scroll problem, not a motion problem.** Expanding a panel must not move the content the reader is looking at, so anchor the scroll position to the toggled element. That is an anchor, not an animation.

## Geometry and density

Radius is zero. `border-radius: 50%` survives for genuinely circular things only: status dot, radio dot, Area chip, avatar. It does not cover spinners, because nothing spins.

Shadows have no blur. There is one hard offset, used on overlays that must lift off the page: dialog and command palette. Never a block, never a card, never a button.

Snap is **15 minutes**, and it is measured rather than chosen: in a real reference month every timed block began and ended on a quarter hour, 92% of them on the hour or half hour, and not one at `:05`, `:10` or `:20`. Grid hairlines are drawn at the hour, with the quarter-hour subdivision revealed only during a drag.

Spacing uses the stock 4px scale wherever it fits, but the rhythm of this system is odd rather than even: 3, 5, 7, 9, 11, 13, 15. Arbitrary values are banned: a value not on the scale becomes a token first.

## Charts

**Area ink encodes identity. Cobalt encodes magnitude and direction.** That single rule assigns every chart in the product.

| Job | Form | Ink |
|---|---|---|
| Composition now | a pie, wedges hatched | Area ink |
| Trend over time | stacked bars by week | Area ink |
| Actual against target | signed deviation bars off a zero rule | cobalt only |
| A bounded meter (parameter maturity, floor progress) | block characters | cobalt only |

Three consequences.

**Trend over time is stacked bars, not a line chart.** A line is neither a wedge nor a bar fill, so the Area seal does not permit ink on it, and twelve cobalt lines separated only by dash pattern is unreadable.

**Direction is never a hue.** Under target extends left of the zero rule, over target extends right, and the sign is a `+` or a minus. Never green for up and red for down.

**Bounded scales get block characters; arbitrary magnitudes get a fill.** A meter is bounded 0 to 100% and the segmented look is the aesthetic. A ranked bar carries arbitrary magnitude, where about 22 discrete steps collapse every non-leading row to a one-cell stub, so it is a single fill whose width is a percentage. That is a rectangle, not a chart, and it needs no library.

Pie and wedge labels sit **outside** the wedge. A wedge fill only has to clear 3:1 as an indicator; text on it would need 4.5:1.

**A deviation row carries no Area ink at all, including its label column.** See [the Area ramp](#the-area-ramp): a chart row is a chart context end to end.

## The budget denominator

Budget percentages are measured against **discretionary time**, which is total time minus the circadian frame, minus external anchors, minus anchor shadows. The residual is **shown, not hidden**: an `Unallocated` wedge sits on the pie and an `Unallocated` row sits in the deviation bars.

That is a design decision with teeth. Measuring against *scheduled* time instead would inflate every Area's share by excluding exactly the hours the user never planned, and the report would read as healthy while the gap grew. It also means the largest wedge on the pie is frequently "nothing planned", which looks like a bug until it is labeled, so it is labeled.

It has one hard prerequisite: **`Routine` is a span, not a marker.** A `Sleep` routine of `23:00 + 8h` bounds the day. Without a duration on the frame, discretionary time cannot be computed at all.

## Illustration

Illustration is generated, not licensed per asset. A local script takes a public-domain source image and outputs a dithered plate in the house style, and it keeps a manifest recording each plate's source and licence.

Subjects are **horological and astronomical instruments**: orreries, sundials, escapement mechanisms, star charts. Thematically exact for a scheduler.

Illustration appears in five places: the first-run wizard, the Areas header band, the weekly-session header, empty states, and error screens.

**It never sits behind the week grid, the Today ledger, or a chart.** The grid is the densest surface in the product and it gets no ornament at all.

## Icons

Standard lucide stroke weight at three sizes: 14, 16 and 20. Caps and joins are round, set by `--icon-cap` and `--icon-join`. This is the one rounded form the system tolerates. Components read the tokens rather than restating the values, because the inherited language's two reference sheets diverged once when its tokens were silent on caps.

Icons pair with an uppercase label in navigation, and a count sits at the right edge of the row. Typographic marks are used inline where a glyph beats an icon.

**One glyph, one meaning.** The origin marks, the pinned mark and the proposal-source mark must not collide, even where they appear at different tiers and can never co-render.

## Keyboard

The product is keyboard-first. Bindings are vim-style single keys, with a `g` prefix for navigation.

| Keys | Action |
|---|---|
| `j` `k` | previous and next block |
| `h` `l` | previous and next day column |
| `[` `]` | previous and next week |
| `T` | jump to today in the grid |
| `z` | cycle visible hours |
| `p` | pin or unpin |
| `Shift+↑` `Shift+↓` | move by 15 minutes and pin. the keyboard equivalent of the drag |
| `Enter` | open the detail panel |
| `c` | confirm the day |
| `x` | mark skipped. `Shift+X` partial, with minutes |
| `n` | capture a task |
| `/` search · `?` help · `Cmd/Ctrl+K` palette | |
| `g` then `w t b a m l s` | the seven screens |
| `Shift+A` | approve all pending proposals |

**The keyboard reaches every block at every tier.** `j` and `k` do not care how tall a block is, so the smallest block in the week is exactly as reachable as the largest. That matters more than the pointer path, because a 9.8px pointer target is genuinely small.

Key hints take one form everywhere: bracketed bare mono text, as in `[ j ]`. This matches the `[ + ]` and `[ - ]` disclosure marks. A bordered key cap is not used, because a border plus brackets at 10px is redundant and two forms for one idea is one too many. **The one form takes the ink of the surface it lands on**, which is what lets it sit inside the control it triggers: `--ink-deep` on paper, `--on-ink` inside an ink-filled button, `--ink` inside a bare one, and `--text-muted` inside a disabled control.

## Token architecture

Three layers, in `frontend/src/tokens/`:

**Layer 0, primitives.** Raw pigment ramps: cobalt, cream, the three signals, and the twelve Area pigments. No meaning and no usage guidance. No component may reference these.

**Layer 1, semantic.** What each value means, and where the seals are written. Tailwind's theme keys map to this layer, so a component writes `bg-paper` or `text-ink`.

**Layer 2, component.** Domain specifics, co-located with the component that needs them. The week grid's geometry currently sits in layer 1 as an interim measure and moves down when the grid component is written.

**A value used by more than one sheet is a token, without exception.** Four values were found re-derived across sheets during the build and promoted: the overlay scrim, the hatch's lightening step, the verdict panel's fixed height, and the reason record's clause-label column. The last one had independently acquired three different widths in three sheets, which is exactly the drift the inherited language warned about when its own two references disagreed on a value the tokens were silent about.

**A broken comment in a token file is a silent, total failure.** A prose paragraph accidentally left outside a `/* */` pair is a CSS parse error, and it discards every token declared after it. That happened once during design: `--block-h-label` resolved to nothing, every block computed as a sliver, and the sheets rendered a plausible-looking grid with no titles at all. So token files are validated mechanically: balanced comments, every statement inside `:root` a real custom-property declaration, no duplicates, and every `var()` reference in every reference sheet resolving against the token files.

## The reference sheets

Five artifacts in `docs/design/`, all of which **link** the token files rather than copying values, so a value cannot drift between the reference and the build.

| Sheet | What it is for |
|---|---|
| `specimen.html` | every token, rendered, with a computed contrast ledger |
| `components.html` | the component inventory, each with a build spec naming the tokens it consumes |
| `screens.html` | all seven routes, their modes, first run and the overlays, assembled |
| `decisions.html` | a live click-through for the choices that are still open |
| `scratch/block-states.html` | the record that settled the block's state channels, the Area ramp and overlap |
| `scratch/week-density.html` | the record that settled the width policy, the tier ladder and the reason record |

The two `scratch/` records are **probes**: they settled a decision by building the alternatives and choosing from rendered output rather than from description. Each states what it settled and what it handed forward. Unlike the inherited language's scratch records, they were revised as decisions changed, so they do not lag this document.

Six decisions in this document were reversed by rendering them, and each reversal is recorded in the sheet that caused it:

- the block title went from 9.5px to 11.5px, then gained a compact tier, because unlabeled fifteen-minute blocks read as a rendering fault;
- the grid dropped from two cobalt lines an hour to one, and the block from four edges to three, because the blocks disappeared into the corduroy. The quarter-hour subdivision was removed in that round and then restored, because the subdivision was never the problem: the weight was;
- `--bp-wide` moved from 1440px to 1536px, because a computed ledger showed 15 characters where the policy needs 17;
- `white-space: nowrap` was removed, because 4 of 37 real titles became ambiguous under end-ellipsis;
- the frame's full-width backdrop rule was deleted in favor of sweep-and-columns, because it painted over its neighbors;
- `--pigment-area-07` was retuned from 183 to 176 degrees, because a computed hue ledger showed it sitting 13 degrees from `--pigment-area-08`, which is not far enough for two dark colors to separate.

Read the probes for the reasoning. Read the tokens for the values.
