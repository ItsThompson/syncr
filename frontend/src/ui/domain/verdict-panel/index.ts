/* THE VERDICT PANEL: the week's own feasibility, at panel volume in amber, with a fixed height.
 *
 * The two reserved heights live here, in `tokens.css`, promoted out of layer 1 with this component and the summary
 * strip: `--verdict-h` for the panel and `--strip-h` for the strip, so the panel and the strip's verdict cell cannot
 * drift apart.
 */

export { ConcessionRow, type ConcessionRowProps } from "./ConcessionRow";
export { ShortfallRow, type ShortfallRowProps } from "./ShortfallRow";
export { TradeoffRow, type TradeoffRowProps } from "./TradeoffRow";
export { VerdictPanel, type VerdictPanelProps } from "./VerdictPanel";
export {
  formatMinutes,
  provenanceReading,
  verdictDetail,
  verdictHeadline,
  type PanelVerdict,
  type ShortfallKind,
  type TradeoffKind,
  type VerdictConcession,
  type VerdictProvenance,
  type VerdictShortfall,
  type VerdictTradeoff,
} from "./verdict";
