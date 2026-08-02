import { useLocation } from "react-router";

import { returnPathFrom } from "../app/signIn";
import { RouteBand } from "./RouteBand";

export function SignInRoute() {
  const location = useLocation();

  return (
    <RouteBand title="Sign in">
      <p className="text-base text-ink-soft">
        Signing in returns to <code className="text-sm">{returnPathFrom(location.search)}</code>.
      </p>
    </RouteBand>
  );
}
