/* WHERE CAPTURE IS REACHED FROM, WHICH IS EVERY SCREEN.
 *
 * ONE INSTANCE, HELD BY THE SHELL. `n` is global because capture must never compete with the thing being
 * captured, and a second instance mounted by the Backlog screen would mean two dialogs could be open at once
 * and two forms could hold two drafts. So the host is mounted once above the route and a screen asks it to
 * open, which is what this context is for.
 *
 * A CONTEXT RATHER THAN A PROP, because every screen can open it and only one of the seven renders a control
 * for it: threading a callback through the shell, the outlet and each route would put capture in six files
 * that do not use it.
 *
 * THE DEFAULT DOES NOTHING AND SAYS SO. A component rendered outside the host has no capture to open, which is
 * true of the sign-in screen: it sits outside the gate, and a visitor with no session has no Area to capture
 * into. `isAvailable` is what lets a control not draw itself rather than draw one that does nothing. */

import { createContext, useContext } from "react";

export interface Capture {
  /** Opens capture, optionally on an Area the caller already knows. */
  readonly open: (areaId?: string) => void;
  /** False outside the host, which is where nothing can be captured. */
  readonly isAvailable: boolean;
}

const NOT_AVAILABLE: Capture = {
  open: () => undefined,
  isAvailable: false,
};

export const CaptureContext = createContext<Capture>(NOT_AVAILABLE);

/** The capture the shell is holding, or one that cannot be opened outside it. */
export function useCapture(): Capture {
  return useContext(CaptureContext);
}
