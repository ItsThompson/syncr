/* The gate in front of the shell.
 *
 * Four states, from one discriminated resource, and the distinction between two of them matters:
 *
 *   loading   a static reading. There is no spinner in the kit to hide the gap
 *   signed out (a 200 with no session, or a 401) redirect to sign-in
 *   error     a statement. NOT a redirect: sending a signed-in user through the login flow
 *             because the api was briefly unreachable would lose their place for a network blip
 *   ready     the shell
 *
 * The redirect carries the requested route in the query string, so the return survives leaving the
 * application, and it replaces the history entry so the back button does not walk into the gate. */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import type { Session } from "../api/hooks/useSession";
import type { Resource } from "../api/resource";
import { signInTarget } from "./signIn";

export interface AuthGateProps {
  readonly session: Resource<Session>;
  readonly children: ReactNode;
}

export function AuthGate({ session, children }: AuthGateProps) {
  const location = useLocation();

  if (session.status === "loading") {
    return (
      <p className="px-3.75 py-2.75 text-eyebrow tracking-eyebrow uppercase text-text-muted">
        reading your session
      </p>
    );
  }

  if (session.status === "error") {
    return (
      <p className="px-3.75 py-2.75 text-base text-ink-soft">{session.problem.detail}</p>
    );
  }

  if (session.data === null) {
    return <Navigate to={signInTarget(`${location.pathname}${location.search}`)} replace />;
  }

  return children;
}
