/* THE WEEKLY SESSION'S OWN SURFACE: the raised-items panel, and the shape it renders.
 *
 * One component, because the session is a MODE and most of what it draws is the Week screen's own: the verdict panel,
 * the grid, the summary strip and the pin path are all ticket 49's and are reused rather than restated. What this family
 * adds is the one surface the screen does not have outside the session.
 */

export { RaisedPanel, type RaisedPanelProps } from "./RaisedPanel";
export { groupRaises, type RaiseGroup, type SessionRaise } from "./raises";
