/* Rendering the real route table at a chosen path.
 *
 * A memory router over the same `routes` the browser router is built from, so a test cannot
 * pass against a route table the application does not use.
 *
 * Each render gets its own SWR cache. A shared cache would let one test's response satisfy the
 * next test's hook, and retries are off so a stubbed failure is a failure once. */

import type { ReactElement } from "react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { render, screen, type RenderResult } from "@testing-library/react";
import { SWRConfig } from "swr";

import { routes } from "../routes";

export function withFreshCache(children: ReactElement): ReactElement {
  return (
    <SWRConfig
      value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}
    >
      {children}
    </SWRConfig>
  );
}

export function renderAt(initialPath: string): RenderResult {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(withFreshCache(<RouterProvider router={router} />));
}

/* Every screen sits behind the gate, so a test about the shell has to wait for the session read
 * before the sidebar exists. Waiting on the sidebar rather than on a timer means the wait is the
 * condition itself. */
export async function renderSignedInAt(initialPath: string): Promise<HTMLElement> {
  renderAt(initialPath);
  return screen.findByLabelText("Screens");
}
