/* The gated shell: the element every screen's route nests inside.
 *
 * AuthGate wraps ShellLayout rather than the other way round, so the sidebar and the keyboard map
 * do not exist for a visitor with no session. This is where the read happens; everything below it
 * takes the resource as a prop and is testable without a network fixture. */

import { useSession } from "../api/hooks/useSession";
import { ShellLayout } from "../ui/domain/shell";
import { AuthGate } from "./AuthGate";

export function GatedShell() {
  const session = useSession();

  return (
    <AuthGate session={session}>
      <ShellLayout />
    </AuthGate>
  );
}
