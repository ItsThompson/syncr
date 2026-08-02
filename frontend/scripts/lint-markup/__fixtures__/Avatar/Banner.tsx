/* Fixture: a file INSIDE a directory named after an allowlisted element, whose own filename is not
 * on the list. The allowlist matched a path substring before, so every file under `Avatar/`,
 * `AreaChip/` or `Radio/` was allowed a circle. The design language closes the list at four
 * elements, not four directories. */

export function Banner() {
  return <div className="rounded-full bg-paper-raised" />;
}
