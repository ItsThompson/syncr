/* WHERE A BANNER-VOLUME NOTICE RENDERS, ASKED OF THE RENDERED SHELL RATHER THAN OF WHATEVER COMPOSED IT.
 *
 * Two suites drive a banner from opposite ends: the notice source's own, and the capture flow that raises the
 * first one a write composes. Both have to ask the same question, which is what is standing in the top bar's
 * slot, so the query is written once. A suite that read the store instead would pass while the top bar rendered
 * nothing. */

import { screen } from "@testing-library/react";

/** The strips standing in the top bar's slot, in the order a reader meets them. */
export function bannersInTheTopBar(): HTMLElement[] {
  return [...screen.getByLabelText("Notices").querySelectorAll<HTMLElement>(".notice--banner")];
}

/** The title of each, which is how one condition is told from another. */
export function titlesInTheTopBar(): (string | undefined)[] {
  return bannersInTheTopBar().map((banner) => banner.querySelector("b")?.textContent ?? undefined);
}
