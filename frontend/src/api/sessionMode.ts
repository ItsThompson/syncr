/* WHETHER THE WEEKLY SESSION IS OPEN, WHICH ONE MODE DECLARES AND ONE MIDDLEWARE READS.
 *
 * Only the caller knows whether the weekly session is open, because it is a mode of this client's own screen
 * rather than a state the api holds. A verdict transition recorded during a session is what the early-catch product
 * metric's numerator counts, so the answer has to cross the wire on every mutation the mode makes.
 *
 * THE FLAG IS HERE AND THE MIDDLEWARE THAT SENDS IT IS IN `client.ts`, which is the direction that has no cycle: the
 * client reads this module, this module reads nothing. It also puts the header beside the credential policy, which is
 * already set there for the same reason -- "so a new hook cannot forget it".
 *
 * A MODULE-SCOPED FLAG RATHER THAN REACT STATE, deliberately. The value is read inside a request builder, which is not
 * a render: a hook could not be read from there, and threading it through would put the mode in the signature of every
 * write hook on the screen. Two tabs are two documents and therefore two modules, so a session open in one tab does
 * not mark the other's mutations -- which is the honest answer, since the mode is a property of a screen.
 *
 * ABSENT RATHER THAN FALSE OUTSIDE A SESSION, which is the shape the api reads: it treats an absent header as false,
 * and that is what every non-browser caller is. Sending `false` would be a second spelling of one statement, and the
 * two must not be distinguishable at a call site, because a call site that could send either can send the wrong one. */

/** The header the api reads off the request. Not in the document, so not in the generated types. */
export const SESSION_MODE_HEADER = "X-Syncr-Session-Mode";

/** The one value ever sent. The api accepts several spellings; a client that used two would be two clients. */
export const SESSION_MODE_OPEN = "true";

let isOpen = false;

/**
 * Declare whether the weekly session is open on this document.
 *
 * Called by the mode as it mounts and as it leaves, so a reader who leaves the session stops marking their mutations
 * without any call site knowing the mode exists.
 */
export function setSessionModeOpen(open: boolean): void {
  isOpen = open;
}

/** Whether a mutation issued now would state that a session is open. */
export function isSessionModeOpen(): boolean {
  return isOpen;
}
