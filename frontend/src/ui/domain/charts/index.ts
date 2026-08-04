/* THE CHARTS. Five of them, and the legend the two Area-inked ones are read with.
 *
 * ONE RULE ASSIGNS EVERY CHART IN THE PRODUCT: Area ink encodes identity, cobalt encodes magnitude and direction.
 *
 *   PieChart       composition now         Area ink, wedges hatched, labels outside
 *   StackedBars    trend over time         Area ink, hatched, by week
 *   AreaLegend     the wedge ledger        a chip, the Area's name, and the figure
 *   DeviationBar   actual against target   COBALT ONLY, including the label cell
 *   DataBar        a ranked magnitude      cobalt, one fill at a percentage width
 *   MaturityMeter  a bounded fraction      cobalt, block characters
 *
 * THERE IS NO LINE CHART, AND THE ABSENCE IS THE DECISION. The ramp is sealed to two chart carriers, a pie wedge
 * fill and a stacked bar fill, so a time series drawn as a line has no legal ink at all; and twelve cobalt lines
 * separated only by dash pattern is unreadable. `__tests__/charts.test.tsx` asserts this family exports none and
 * draws no polyline, because an absence with no check is an absence that comes back.
 *
 * THE TWO BOUNDED-PROGRESS FORMS ARE DELIBERATELY DIFFERENT AND MUST NOT BE UNIFIED. `MaturityMeter` is bounded 0
 * to 100%, so a segmented run of block characters reads as a fraction of something. `DataBar` carries an
 * arbitrary magnitude, where fourteen discrete steps would collapse every non-leading row to a one-cell stub, so
 * it is a single fill at a percentage width. Each file states its half of that reasoning where a reader will meet
 * it.
 *
 * HATCH USE 1 OF 3 LIVES HERE. The product's three uses are Area redundancy on a chart fill, an external
 * anchor's fill, and a forbidden window. There is no fourth, which is why `Unallocated` takes a flat fill: it
 * holds no Area, so there is no identity for a texture to be redundant about.
 *
 * NO `Plate` GOES BEHIND A CHART. Illustration belongs in headers, empty states and dead space; the charts and
 * the grid get no ornament at all. Nothing here can place one: the layer's plate is an `img` in the flow. */

export { AreaLegend, type AreaLegendProps } from "./AreaLegend";
export { DataBar, type DataBarProps } from "./DataBar";
export { DeviationBar, type DeviationBarProps } from "./DeviationBar";
export { MaturityMeter, type MaturityMeterProps } from "./MaturityMeter";
export { PieChart, type PieChartProps } from "./PieChart";
export { StackedBars, type StackedBar, type StackedBarsProps } from "./StackedBars";
export { WedgePatterns, patternId, type WedgePatternsProps } from "./WedgePatterns";

export { AREA_HATCHES, HATCH_GEOMETRY, HATCH_NAMES, hatchFor, type HatchName } from "./hatch";
export { MINUS_SIGN, plotDeviations } from "./deviation";
export { PIE, layOutPie, type PieLayout, type Wedge } from "./wedges";
export {
  UNALLOCATED,
  type AreaLegendEntry,
  type AreaQuantity,
  type ChartPigment,
  type DeviationRow,
  type FigureFormat,
} from "./series";
