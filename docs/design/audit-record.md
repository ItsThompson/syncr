# The accessibility and degradation audit

The cross-surface audit section 19's error matrix, section 16's notice volumes and section 14's review
checklist ask for. It records **which mechanism answers each question**, because a checklist walked by
a person is a second copy of a fact: the answers below are produced by gates that fail, not by
statements somebody made.

Every figure here is measured by something in the tree. Where a claim cannot be mechanised, it says
so, and where a claim is narrower than the rule it serves, it says that too.

## The operation-to-state matrix

Section 19 lists eleven operations, each with a loading, an empty and an error state, and states that
**no entry is a spinner, a skeleton or a progress bar**.

| Question | Answered by |
|---|---|
| Does every screen render a static, announced surface while its reads are outstanding? | `frontend/src/routes/__tests__/errorMatrix.test.tsx`, over every path in `SCREENS` plus setup and the root redirect, with every api read answered as outstanding at once |
| Does every screen render its failure in the api's own words? | the same sweep, with every api read refused |
| Does anything anywhere claim to be in motion? | `indicatorsIn` over the rendered tree in each of those cases, and `e2e/tests/s22-no-motion.spec.ts` over the computed style of every element on eleven routes |
| Does the kit even have a spinner to reach for? | `frontend/src/ui/notBuilt.test.ts`, over the three barrels' export surface: the three named absences, plus any export named from the vocabulary of motion |
| Are the empty states the matrix names rendered with their repairs? | `errorMatrix.test.tsx`: both `emptyReason` states of the week with their actions, the backlog's capture prompt, a day with no block, `Collecting baseline` asserted to carry no failure surface, and the pie review's statement |

**The reads are not enumerated and neither are the screens.** Settings makes six reads and Templates
nine; a list of them would still pass the day a screen gains a tenth. The sweep answers every api read
at once by prefix, and takes its paths from the table the sidebar renders and the keyboard chords
resolve against, so an eighth screen is covered the day it exists.

**Shown to fail:** removing the pending surface's `role="status"` reddens eleven of the sweep's thirty
cases.

## The degradation notices

| Question | Answered by |
|---|---|
| Does every notice name a capability that survives it? | the kit's non-empty tuple at compile time, the api's Pydantic validator before serialization, and `frontend/src/routes/__tests__/noticeVolumes.test.ts`, which parses every notice the application declares out of its own source |
| Which notices exist at all? | the same parse: an object literal carrying a `volume` and a `stillWorks`, found by the TypeScript parser rather than by a pattern over `volume:`, which also matches prop types and doc comments |
| Does each case take the volume and pigment section 16 assigns it? | `noticeVolumes.test.ts` calls the factory each screen calls, for thirteen cases |
| Is level 4 unused? | the volumes the tree declares are the three, asserted over the parsed set; the kit exports no blocking notice and no dialog for one |
| Does the write-target expiry take the loudest non-blocking volume, with one repair? | `frontend/src/routes/__tests__/degradation.test.tsx`: a banner in oxide, the duration in its first sentence, exactly one link, and no dismiss control |
| Does a failed solve state that no plan was produced, with the attempt count, over the plan it did not replace? | the same file, driven by a `failed` operation over the real event stream |
| Does an unreadable feed reach the day its commitments came from? | the same file: an inline amber notice on a day holding an imported commitment, and nothing on a day holding none |
| Does a pushed notice reach the reader? | the same file: a `notice` event invalidates the resource whose read composes the words, and the banner appears without a reload |
| Only conflicts notify | the same file, over the stream's own event union, partitioned into the types that interrupt and those that do not, with both conditions standing before each push |

**A notice whose capability list this cannot read is reported as unresolved rather than as satisfied.**
Eighteen composed notices across eight modules today, plus the one module that narrows a wire notice
into the kit's type, which is declared and asserted to be one module.

**Shown to fail:** emptying one module's capability list reddens two cases; reverting the pushed-notice
wiring reddens two; reverting the stale-feed notice reddens one.

## Motion

| Claim | Answered by |
|---|---|
| No transition, animation or transform in any stylesheet the repository writes | stylelint's `property-disallowed-list`, from the one module the four consumers share |
| None in the stylesheet a browser downloads | `frontend/scripts/check-bundle`, declaration by declaration with postcss |
| No keyframe list in that stylesheet | the same gate, over at-rules: every frame of an animation is a legal declaration on its own, so the at-rule is what has to be refused |
| `--duration` is `0s` in the shipped artifact | `frontend/src/builtStylesheet.test.ts`, read out of the built bundle rather than out of `layout.css` |
| Nothing moves in a real browser | `e2e/tests/s22-no-motion.spec.ts`, over `transitionDuration` and `animationName` of every element on eleven routes |
| Progress is a count that changes | the failed-solve panel states its attempt count; the projection notice states attempt N of M; `MaturityMeter` is block characters and states its figure beside them |

**There is nothing to respect a reduced-motion preference for.** `--duration` is `0s`, no keyframe list
ships, and no property that could animate is permitted anywhere. A media query would be a second
statement of a rule already absolute, and the absence of one is the strongest compliance available
rather than an omission.

**Expanding a panel anchors the scroll position to the toggled element.** Instant collapse is a scroll
problem rather than a motion problem: the accordion measures its trigger before and after the layout
changes and takes the difference out of the scroll position, in a layout effect so the correction lands
in the same frame. No screen mounts that component yet, so the arithmetic is asserted in jsdom with the
two measurements supplied and there is no browser pass for it.

## Colour and contrast

| Claim | Answered by |
|---|---|
| Every colour pair has a computed ratio against every surface it can reach | `docs/design/contrast-ledger.md`, generated from the token files: 484 pairs, 22 inks against 22 surfaces, read from 42 shipped stylesheets |
| A pair without a ratio fails the audit | `frontend/scripts/audit-contrast`, which regenerates the ledger and refuses a difference, and reports any value that resolves to no colour |
| A control's border clears 3:1 on every surface a control can sit on | the same gate, asserted per paper surface |
| `--rule-strong` is banned on controls | the same gate, as a MEASUREMENT: it is refused because it measures 2.65:1 there, and a retune ABOVE the floor reports that the ban needs revisiting rather than being kept quietly |
| Text clears 4.5:1 on every surface it can appear on | the same gate, for the three label inks on both paper surfaces |
| Amber has no text step | `frontend/src/ui/domain/__tests__/pigment.test.ts`: 4.52:1 on raised paper and 4.18:1 on the page, so a label passes on one and fails on the other; and no rule in the kit puts a signal pigment on anything that is not a mark |
| Secondary text on a signal wash steps to `--ink-soft` | the same file: `--text-muted` measures 4.31:1 on `--amber-wash`, and no rule that fills with a wash pairs it with `--text-muted` |
| Colour is never the only encoding | every chart fill pairs with a hatch, asserted in `charts/__tests__`; every Area chip pairs with the Area's name, asserted in `marks/__tests__`; a deviation row carries no Area ink at all and direction is a side and a sign |

**Which floor a row is held to is classified by the property that writes it,** and the ledger names the
declaration that set each one so the classification is checkable. A `color` on a rule that also paints
a hatch is a carrier for the hatch's own `currentColor` rather than text, and is held to the indicator
floor for that reason. A GLYPH is a mark and its own floor is 3:1, which no property can distinguish
from a label: an ink used only on a mark is therefore shown against the stricter floor, and the
structural rule that no prose may take a signal pigment is what carries that half.

**313 of the 484 pairs do not clear the ink's floor and that is not 313 defects.** `--on-ink` on
`--paper` is 1.08:1 and could not be otherwise: it exists for an ink-filled surface, and an Area pigment
as a chart fill is a surface no label ever lands on, because a pie chart's labels sit outside its
wedges. What the ledger refuses is a pair with no ratio at all.

## Keyboard and focus

| Claim | Answered by |
|---|---|
| Every block is reachable by keyboard, at every tier the grid renders | `e2e/tests/s21-keyboard-and-focus.spec.ts`, with the tiers read off the grid rather than named, and focus following selection |
| A block 8 to 13 pixels tall is reachable | `frontend/src/ui/domain/week-grid/__tests__/block.test.tsx`, by role, at that exact height, against the real component. **No seeded fixture renders one**, so the browser pass does not reach it: ticket 1561 |
| A whole planning session completes without the pointer | `s21-keyboard-and-focus.spec.ts`: `g w`, `j`, `Shift+Down` with the pin read back over the api, `n` with the caret in the field, `c`, `Shift+A` |
| Focus order follows visual order on every screen | the same file, per screen, against the boxes the browser reports |
| Every interactive element shows a focus ring at a 2px offset, chosen by the surface | the same file, as a computed value: 2px at 2px, in the standard ink on paper and the inverse ink inside an ink-filled container |
| The inverse ring is scoped to containers rather than controls | `frontend/src/builtStylesheet.test.ts` reads `.on-ink-surface :focus-visible` out of the artifact, so a control added to such a surface later inherits it |

**Two false reports were measured while building the focus-order check, and each taught the instrument
something.** A column break is not a backward step: the sidebar's rows precede the route's content in
the DOM, so tabbing off the last one goes to the top of the main column, which is higher and further
right. And two elements are on one row when their vertical extents OVERLAP, not when their tops are
within a row height, which had called a tab panel beginning 27px under its own strip a defect.

## Forced-colors mode

| Claim | Answered by |
|---|---|
| Every block state except hover survives, asserted per state | `forcedColorsCasualties` over each layer's stylesheets, per state, in the three `layerRules` tests |
| The one further casualty is named rather than papered over | the frame's recessed fill: what identifies a frame block when the OS drops every fill is its origin mark and its own title, both of which are text. Adding a border to satisfy the check would distinguish nothing |
| A state survives in a real browser | `s21-keyboard-and-focus.spec.ts` enters forced-colors mode and measures a selected block against an unselected one: the two fills are equal because the mode drops them, and the 3px left rule is what distinguishes the state |
| Hover is mouse-only and nothing depends on it | the state vocabulary gives hover the fill channel alone, and every operation in the product has a keyboard path, which S21 drives |

## Section 14's review checklist

Seven questions, applied to every kit component by a mechanism over the whole kit rather than by a
per-component walk. A per-component table would be sixty rows of somebody's opinion; each row below is
a gate.

| Question | Answered by | Verdict |
|---|---|---|
| Does every state read from an attribute in the closed vocabulary? | `lint:markup`, over every source file and every stylesheet | 16 attributes, closed |
| Does any new colour pair have a computed ratio against every surface it can reach? | `lint:contrast` and the committed ledger | 484 pairs |
| Is any new interaction state validated in combination? | `primitives/__tests__/stateCombinations.test.tsx` and `visualState`'s signature comparison, which refuses two combinations that render identically | no two combinations share a signature |
| Does the component read tokens rather than restating their values? | each layer's `layerRules` test: no colour restated, no layer 0 ramp step reached | clean in all three layers |
| Did this component leave a layer 1 token behind that should have moved to layer 2 with it? | `frontend/src/ui/layerTwo.test.ts`: each promoted token is declared by the component that owns it and by no file in the token layer, and the token layer still points at each new home | all three groups promoted, no copy left behind |
| Does the component survive forced-colors mode, or is its one casualty hover? | `forcedColorsCasualties` per layer | hover, plus the frame's fill, named above |
| Is every claim in a comment provable? | not mechanisable in general. What IS mechanised: every ratio in the tree is computed by the contrast reader, every rendered-pixel figure by `lint:render`, and every "measured" figure in this document by the gate named beside it | partly |

## What this audit does not cover

Stated plainly, because an overstated bound is worse than a stated gap.

| Gap | Why | Where it should land |
|---|---|---|
| The sliver tier in a browser | No seeded week holds a block short enough to render between 8 and 13px at any available zoom, measured across the whole ladder | ticket 1561 |
| The stale-feed notice on the week screen's day headers | The day header is `--day-header-h` tall and holds a label and a count; an inline notice does not fit without changing the grid's settled geometry. The day-scoped notice ships on Today, which is the surface a reader answers for a day on | ticket 1560 |
| The accordion's scroll anchoring in a browser | No screen mounts the component yet, so there is nothing to drive | ticket 1562 |
| A screen reader | No assistive technology is driven anywhere in this repository. What is asserted instead is the accessible tree: roles, names, `aria-*` state, and the announcements a pending or failed surface carries | not filed: it needs a real screen reader and a person |
| The api's own problem-type inventory | The api publishes no catalog of problem types, so a client's error map cannot be bounded by it | ticket 1502 |
| Two raw `z-index` values in four sheets | No token ladder for stacking order, which is what produced item 46's scrim defect | ticket 1461 |
