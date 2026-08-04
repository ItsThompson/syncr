/* Driving one stepped figure by the member it belongs to, rather than by its position.
 *
 * A stepper renders two buttons named `increase 15 minutes` and `decrease 15 minutes`, and every stepper on a
 * form renders the same two. An index into all of them is a proxy for the member: it drives the right control
 * only while the form's order holds, and when it breaks the failure message names the step rather than the
 * member, which sends a reader to the wrong row. This finds the figure by its own accessible name and then the
 * button beside it.
 *
 * The container is the field's parent because that is what the kit's stepper IS: the buttons and the figure are
 * siblings inside one span. No class name is read, so the test does not depend on the kit's spelling. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

export type StepDirection = "increase" | "decrease";

/** The stepper for the row a label names. */
function stepperFor(label: string): HTMLElement {
  const figure = screen.getByRole("spinbutton", { name: label });
  const stepper = figure.parentElement;
  if (stepper === null) throw new Error(`the ${label} figure sits in no stepper`);
  return stepper;
}

/** Steps the figure a label names, once. */
export async function step(label: string, direction: StepDirection): Promise<void> {
  const control = within(stepperFor(label)).getByRole("button", {
    name: `${direction} 15 minutes`,
  });
  await userEvent.click(control);
}
