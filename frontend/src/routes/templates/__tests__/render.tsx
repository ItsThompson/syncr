/* Rendering one tab on its own.
 *
 * A tab holds a real link to setup, and a `Link` outside a router throws, so the router is the whole of what
 * this adds. Nothing here supplies data: a tab takes its resources as props, which is what lets a component
 * test drive a boundary without a network fixture. */

import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

export function withRouter(element: ReactElement): ReactElement {
  return <MemoryRouter>{element}</MemoryRouter>;
}
