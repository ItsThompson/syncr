/* THE FOUR LEGAL CIRCLES, AND THE ONE PLACE THE ALLOWLIST IS WRITTEN.
 *
 * Radius is zero and 50% survives for the status dot, the radio dot, the Area chip and the avatar. Two
 * rules ask that question of two different inputs, a `rounded-full` utility in a class list and a
 * `borderRadius: "50%"` in an inline style, and an inline style defeated both when the list lived beside
 * only one of them.
 *
 * MATCHED ON THE FILENAME, NOT ON THE PATH. `file.includes(name)` gave every file inside a directory named
 * `AreaChip/` or `Avatar/` a circle, which is not what the design language closes the list at. */

import path from "node:path";

export const CIRCLE_ALLOWLIST: ReadonlySet<string> = new Set([
  "StatusDot",
  "RadioDot",
  "AreaChip",
  "Avatar",
]);

export function isCircleAllowed(file: string): boolean {
  return CIRCLE_ALLOWLIST.has(path.basename(file, path.extname(file)));
}
