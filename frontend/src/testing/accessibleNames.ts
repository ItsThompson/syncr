/* WHO AUTHORS THE WORDS, read off a render rather than counted by eye.
 *
 * A control that a screen draws the question for can be named two ways, and a rendering looks the same
 * either way: the question is on the screen and the control answers to it. What differs is how many times
 * the words were WRITTEN. A control carrying them in its own `aria-label` beside a screen that draws them is
 * two copies of one string for a reader to keep in step, and it is announced as the drawn text and again as
 * the control's name. A control pointed at the drawn element by `aria-labelledby` is one copy and a
 * reference to it.
 *
 * Chrome reports the distinction directly: the same query over `Accessibility.getFullAXTree` returns a name
 * whose source is `attribute[aria-label]` in the first case and `relatedElement[aria-labelledby]` in the
 * second, with the drawn words present once either way. jsdom applies no accessibility engine, so this reads
 * the two authored forms out of the DOM instead: text an element draws, and the `aria-label` attributes.
 *
 * IT RETURNS WHAT IT FOUND RATHER THAN HOW MANY. A count is satisfied by any two things, so a test asserting
 * "one" cannot say whether the one it got is the element the screen drew or a control's own string.
 *
 * A LABEL THAT POINTS AT NOTHING is read here too, because it is the failure the group form exists to avoid
 * and it is invisible in a rendering. See `ui/primitives/naming.ts` for what a browser computes for the group
 * such a label aims at. */

/** How a node came to carry the words. `aria-labelledby` is absent by design: it is a reference, not a copy. */
export type AuthoredNameSource = "drawn text" | "aria-label";

export interface AuthoredName {
  readonly source: AuthoredNameSource;
  /** The element that carries them, as a reader would recognise it in the markup. */
  readonly by: string;
}

/** An element named the way it is written, so a finding points at a line rather than at a node. */
function shapeOf(element: Element): string {
  const role = element.getAttribute("role");
  const classes = element.getAttribute("class");
  const first = classes === null ? "" : `.${classes.split(/\s+/)[0]}`;
  return `${element.tagName.toLowerCase()}${role === null ? "" : `[role=${role}]`}${first}`;
}

/** The `for` of every label in a render that points at no element, which is a label naming nothing. */
export function danglingLabels(container: HTMLElement): string[] {
  const dangling: string[] = [];
  for (const label of container.querySelectorAll("label[for]")) {
    const target = label.getAttribute("for") ?? "";
    if (container.ownerDocument.getElementById(target) === null) dangling.push(target);
  }
  return dangling;
}

/**
 * The words an element authors ITSELF, which is its own text nodes and not its descendants'.
 *
 * `textContent` is an element's text plus every descendant's, so reading it would report one drawn copy per
 * level of the tree. A leaf test would exclude the ancestors but also the required row, whose label element
 * draws the words beside a marker element and so has an element child.
 */
function ownText(element: Element): string {
  let text = "";
  for (const node of element.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) text += node.nodeValue ?? "";
  }
  return text.trim();
}

/** Every place the words are authored in a render, in document order. */
export function authoredNames(container: HTMLElement, words: string): AuthoredName[] {
  const found: AuthoredName[] = [];
  for (const element of container.querySelectorAll("*")) {
    if (ownText(element) === words) {
      found.push({ source: "drawn text", by: shapeOf(element) });
    }
    if (element.getAttribute("aria-label") === words) {
      found.push({ source: "aria-label", by: shapeOf(element) });
    }
  }
  return found;
}
