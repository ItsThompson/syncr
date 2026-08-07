/* The gated shell: the element every screen's route nests inside.
 *
 * AuthGate wraps ShellLayout rather than the other way round, so the sidebar and the keyboard map
 * do not exist for a visitor with no session. This is where the read happens; everything below it
 * takes the resource as a prop and is testable without a network fixture.
 *
 * THE BANNER VOLUME IS READ HERE, ONE LAYER ABOVE THE KIT. A banner persists until its condition clears and it is
 * about the product rather than about a screen: the write target's token expiring stops the plan reaching the phone
 * whichever screen a reader is on, and it is the most dangerous silent failure syncr has. The kit may not fetch, so
 * the read is here and the notices go down as a prop.
 *
 * THE PUSH CONNECTION IS OPENED HERE, INSIDE THE GATE. One connection for the whole application, because the
 * stream carries every operation, conflict, projection and notice of an account and a second would be a second
 * fan-out and a second thing to reconnect. Inside the gate rather than around it: a visitor with no session has
 * nothing to be pushed. The kit may not fetch, so the provider sits here and a route reads it through a hook.
 *
 * THE WORDS ARE THE API'S. The same condition is composed once and raised at two volumes with a shared identity
 * root: the banner here, and the panel on Settings. Neither surface writes the sentence, so the two cannot state
 * the outage differently. */

import { useGoogleConnection } from "../api/hooks/useCalendarSources";
import { useSession } from "../api/hooks/useSession";
import { EventStreamProvider } from "../api/events";
import { NoticeStrip, noticesAt, ShellLayout } from "../ui/domain";
import { AuthGate } from "./AuthGate";

export function GatedShell() {
  const session = useSession();
  const connection = useGoogleConnection();

  const banners = connection.status === "ready" ? noticesAt("banner", connection.data.notices) : [];

  return (
    <AuthGate session={session}>
      <EventStreamProvider>
        <ShellLayout
          notices={banners.map((notice) => (
            <NoticeStrip key={notice.id} notice={notice} />
          ))}
        />
      </EventStreamProvider>
    </AuthGate>
  );
}
