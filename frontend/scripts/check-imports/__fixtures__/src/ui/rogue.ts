/* Fixture: a kit file in no zone at all.
 *
 * `src/ui/` is the kit, but only `ui/primitives`, `ui/layout` and `ui/domain` are zones. A module
 * directly under `src/ui/` therefore had no `REACHABLE` entry, so the check skipped it: nothing
 * constrained what it imports, and every zone may read it. That is the same hole as an unmodelled
 * destination, seen from the other end. */

export { apiFetch } from "../../api/client.ts";
