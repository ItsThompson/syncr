/* What `keepFrame` means, in both directions, stated once.
 *
 * BOTH MEANINGS ARE STATED WHEREVER THE FIELD IS. The choice is offered at declaration and is
 * editable afterwards, which is two surfaces, and a boolean labelled `keepFrame` on either of them says nothing
 * about what happens inside the span. Two copies of the sentence is how the declaration form and the table come to
 * describe the same field differently, so the sentence lives here and both read it.
 *
 * FALSE IS THE DEFAULT AND IT IS THE LOUDER READING: nothing materializes at all, which is what a holiday abroad
 * is. True is the quieter one: the frame still runs and nothing else does. */

export const KEEP_FRAME_MEANINGS = {
  off: "Off: no routine materializes inside the span either. The holiday-abroad reading.",
  on: "On: your routines still materialize and nothing else does. The quiet-week-at-home reading.",
} as const;
