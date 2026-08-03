/* The shell: the top bar, the sidebar, the notice-strip slot, the route, and the two overlays.
 *
 * It owns the global keyboard map, so a binding cannot be claimed twice by two routes. The
 * SSE connection and banner-volume notices land here too, in the slot the top bar already
 * renders.
 *
 * THE PALETTE'S ACTIONS ARE DERIVED FROM THE SCREEN TABLE, hint included, so the row a reader reads in the palette
 * and the chord the keyboard answers to come from one place. Later tickets add their own actions to this list as
 * they wire the mutations behind them. */

import { useMemo } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";

import { useScreenChords } from "../../../lib/keyboard";
import type { CommandAction } from "../../primitives";
import { CommandPalette } from "./CommandPalette";
import { HelpOverlay } from "./HelpOverlay";
import { SidebarNav } from "./SidebarNav";
import { TopBar } from "./TopBar";
import { SCREENS } from "./navigation";

export function ShellLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  useScreenChords(SCREENS);

  const actions = useMemo<CommandAction[]>(
    () =>
      SCREENS.map((screen) => ({
        id: screen.path,
        label: `Go to ${screen.label}`,
        group: "Navigate",
        hint: `g ${screen.chord}`,
        isCurrent: screen.path === location.pathname,
      })),
    [location.pathname],
  );

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <TopBar />
      <div className="flex grow">
        <SidebarNav screens={SCREENS} currentPath={location.pathname} />
        <main className="grow px-7 py-5">
          <Outlet />
        </main>
      </div>
      <CommandPalette actions={actions} onSelect={(path) => void navigate(path)} />
      <HelpOverlay />
    </div>
  );
}
