/* The route table. APPEND ONLY.
 *
 * Every screen is declared here as a stub, so a later ticket replaces a route's BODY and adds
 * no entry. Adding an entry later would mean a screen could reach the sidebar, or a keyboard
 * chord, without a route to receive it.
 *
 * The screens the sidebar shows are derived from one table (`SCREENS`), and this file asserts
 * that every one of them has a route, so a screen cannot be navigable and unrouted. */

import { type RouteObject } from "react-router";

import { GatedShell } from "../app/GatedShell";
import { SETUP_PATH, SIGN_IN_PATH } from "../ui/domain/shell/navigation";
import { AreasRoute } from "./AreasRoute";
import { BacklogRoute } from "./BacklogRoute";
import { LearnedRoute } from "./LearnedRoute";
import { NotFoundRoute } from "./NotFoundRoute";
import { RootRedirect } from "./RootRedirect";
import { SettingsRoute } from "./settings";
import { SetupRoute } from "./setup";
import { SignInRoute } from "./SignInRoute";
import { TemplatesRoute } from "./templates";
import { TodayRoute } from "./TodayRoute";
import { WeekRoute } from "./WeekRoute";

export const routes: RouteObject[] = [
  { path: SIGN_IN_PATH, element: <SignInRoute /> },
  {
    element: <GatedShell />,
    children: [
      // `/` lands on the week, or on setup when the minimum a plan needs does not exist. The reading
      // that decides between them arrived with the screen that computes it, which is `/setup`.
      { index: true, element: <RootRedirect /> },
      { path: SETUP_PATH, element: <SetupRoute /> },
      { path: "/week", element: <WeekRoute /> },
      { path: "/today", element: <TodayRoute /> },
      { path: "/backlog", element: <BacklogRoute /> },
      { path: "/areas", element: <AreasRoute /> },
      { path: "/templates", element: <TemplatesRoute /> },
      { path: "/learned", element: <LearnedRoute /> },
      { path: "/settings", element: <SettingsRoute /> },
      // Last, and last on purpose: `*` matches whatever the entries above did not, so a typo lands
      // on a syncr surface rather than on React Router's developer error page.
      { path: "*", element: <NotFoundRoute /> },
    ],
  },
];
