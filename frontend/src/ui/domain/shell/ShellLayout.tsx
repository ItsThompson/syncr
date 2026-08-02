/* The shell: the top bar, the sidebar, the notice-strip slot, and the route.
 *
 * It owns the global keyboard map, so a binding cannot be claimed twice by two routes. The
 * SSE connection and banner-volume notices land here too, in the slot the top bar already
 * renders. */

import { Outlet, useLocation } from "react-router";

import { useScreenChords } from "../../../lib/keyboard";
import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";
import { SCREENS } from "./navigation";

export function ShellLayout() {
  const location = useLocation();
  useScreenChords(SCREENS);

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <TopBar />
      <div className="flex grow">
        <SidebarNav screens={SCREENS} currentPath={location.pathname} />
        <main className="grow px-7 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
