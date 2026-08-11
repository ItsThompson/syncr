/* Rendering a byte count the way vite renders one.
 *
 * A kB here is 1000 bytes, which is vite's own convention rather than a choice made twice: the built
 * artifact's figure is read beside vite's build output constantly, and two numbers for one artifact
 * that disagree by 2.4% is a reader checking which tool they are looking at. Stated once, so a second
 * caller cannot state it differently. */

export function asKb(bytes: number): string {
  return `${(bytes / 1000).toFixed(2)} kB`;
}
