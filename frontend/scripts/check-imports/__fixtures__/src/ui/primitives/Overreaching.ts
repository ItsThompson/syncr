/* Fixture: a primitive reaching a layer above it and a type it may not name. */

import { Panel } from "../layout/Panel";
import type { Problem } from "../../contract";

export function Overreaching(problem: Problem): unknown {
  void Panel;
  return problem;
}
