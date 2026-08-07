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

/** What a caller can say about the opening it is asking for. */
export interface CaptureOpening {
  /** The Area to open ON, where the caller already knows it. Not a change to a draft in flight. */
  readonly areaId?: string | undefined;
  /**
   * Where focus returns when the dialog closes. Defaults to wherever the reader was.
   *
   * NAMED BY A CALLER WHOSE OWN CONTROL WILL NOT SURVIVE THE WRITE. The empty backlog's prompt is replaced by a
   * table as soon as the first task lands, so returning to the button that was pressed would return to nothing:
   * it names the band's control instead, which is the same affordance and is always there.
   */
  readonly returnFocusTo?: HTMLElement | null | undefined;
}

export interface Capture {
  /** Opens capture, on the Area and with the focus target the caller names. */
  readonly open: (opening?: CaptureOpening) => void;
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
