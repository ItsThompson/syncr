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
 * A PUSHED NOTICE IS A CONDITION TO RE-READ, NOT WORDS TO RENDER. The api publishes a notice event from the
 * failure that raised it -- a projection that stopped is published by the pass that failed, rather than left for
 * the next read of Settings -- because that is the one degradation a reader cannot discover by looking at the
 * plan: the plan is correct and the calendar is quietly stale. So the event invalidates the resource whose read
 * COMPOSES the notice, exactly as a conflict event invalidates the week. The words stay the api's, written once,
 * and the banner and the Settings panel cannot state the outage differently. Rendering the event's own payload
 * would be a second path to the same sentence, and the first one to drift.
 *
 * THE PUSH CONNECTION IS OPENED HERE, INSIDE THE GATE. One connection for the whole application, because the
 * stream carries every operation, conflict, projection and notice of an account and a second would be a second
 * fan-out and a second thing to reconnect. Inside the gate rather than around it: a visitor with no session has
 * nothing to be pushed. The kit may not fetch, so the provider sits here and a route reads it through a hook.
 *
 * CAPTURE IS HELD HERE FOR THE SAME REASON THE CONNECTION IS. `n` opens capture from any screen, because capture
 * must never compete with the thing being captured, so there is one dialog above the outlet rather than one per
 * screen: two instances would mean two forms holding two drafts of the same task. Inside the gate, because a
 * visitor with no session has no Area to capture into. A screen that wants a control for it asks this instance
 * to open through `useCapture`. It lives in `app/capture/` rather than in a route's directory, because a thing
 * the gate mounts is the shell's: a route importing it is a screen asking for the shell's affordance, and the
 * shell importing a route for a shell-owned concern was the wrong direction.
 *
 * THE WORDS ARE THE API'S. The same condition is composed once and raised at two volumes with a shared identity
 * root: the banner here, and the panel on Settings. Neither surface writes the sentence, so the two cannot state
 * the outage differently. */

import { useCallback } from "react";
import { useSWRConfig } from "swr";

import { useGoogleConnection } from "../api/hooks/useCalendarSources";
import { useSession } from "../api/hooks/useSession";
import { EventStreamProvider, useServerEvents } from "../api/events";
import { googleConnectionKey } from "../api/keys";
import { CaptureHost } from "./capture";
import { NoticeStrip, noticesAt, ShellLayout } from "../ui/domain";
import { AuthGate } from "./AuthGate";

export function GatedShell() {
  const session = useSession();

  return (
    <AuthGate session={session}>
      <EventStreamProvider>
        <CaptureHost>
          <ShellBanners />
        </CaptureHost>
      </EventStreamProvider>
    </AuthGate>
  );
}

/**
 * The shell, with whatever is degraded stated in the top bar.
 *
 * A component of its own because it reads the push connection, and the provider that opens that connection is
 * mounted above it: a hook cannot subscribe to a context its own element declares.
 */
function ShellBanners() {
  const connection = useGoogleConnection();
  const { mutate } = useSWRConfig();

  useServerEvents(
    useCallback(
      (event) => {
        if (event.type !== "notice") return;
        void mutate(googleConnectionKey());
      },
      [mutate],
    ),
  );

  const banners = connection.status === "ready" ? noticesAt("banner", connection.data.notices) : [];

  return (
    <ShellLayout
      notices={banners.map((notice) => (
        <NoticeStrip key={notice.id} notice={notice} />
      ))}
    />
  );
}
