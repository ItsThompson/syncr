/* Fixture: the fetching kit component review iteration 3 built, which passed tsc, oxlint, prettier
 * and vite build. Every spelling of the same capability, so the check is proved against the shape
 * the language permits rather than the shape a table listed. */

import { client } from "../../../api/client.ts";
import { readinessKey } from "../../../api/keys.js";
import { paths } from "../../../api/index";
import type { components } from "../../../api/schema";
import { signInTarget } from "../../../app/signIn";
import { routes } from "../../../routes";

export function Smuggler(): string {
  void client.GET("/readyz");
  void paths;
  void routes;
  void signInTarget("/week");
  return readinessKey();
}

export type Leaked = components["schemas"]["Problem"];
