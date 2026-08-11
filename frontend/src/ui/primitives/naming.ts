/* HOW A CONTROL IS NAMED WHEN NO `<label>` CAN POINT AT IT. This file is where that argument lives; the
 * controls and the form row point here rather than restating it.
 *
 * A radio group's tab stop is a descendant Radix owns, and an interval is a fieldset with two fields of its
 * own. Neither is a labelable element, so a `<label htmlFor>` aimed at one names nothing at all: read out of
 * Chrome's accessibility tree, such a group has an empty name and NO NAME SOURCE, from markup that looks
 * right.
 *
 * That leaves two ways to name one, and a control takes exactly one of them:
 *
 *   label       the words, which the control sets as its own `aria-label`. For a screen that does not draw
 *               the question, so the control is the only place the words exist.
 *   labelledBy  the id of an element the SCREEN ALREADY DREW, which the control points at. The words are
 *               written once and the name is a reference to them rather than a second copy of them.
 *
 * A screen that draws the question and also passes it as a string authors the words twice, and a browser
 * reports both: the drawn text, and the control's own `aria-label` carrying the same string.
 *
 * NEITHER IS NOT A CHOICE. A group with no name is announced by its role alone, so no member of this union
 * lacks one. Both at once is refused as well: two names for one control is two things to keep in step, and
 * the accessible name would come from whichever the browser prefers rather than from the caller's intent. */

export type GroupNaming =
  | {
      readonly label: string;
      readonly labelledBy?: never;
    }
  | {
      readonly label?: never;
      readonly labelledBy: string;
    };
