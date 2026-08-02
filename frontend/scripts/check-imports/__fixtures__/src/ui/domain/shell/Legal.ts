/* Fixture: a domain component reaching only what its zone permits. */

import { Panel } from "../../layout/Panel";
import { Button } from "../../primitives/Button";
import type { Problem } from "../../../contract";
import { useScreenChords } from "../../../lib/keyboard";

export function Legal(problem: Problem): unknown {
  void useScreenChords;
  void Panel;
  void Button;
  return problem;
}
