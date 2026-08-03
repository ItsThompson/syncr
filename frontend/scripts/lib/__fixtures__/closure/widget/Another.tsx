/* A component that loads the widget's sheet alongside a sheet of its own, and it sorts FIRST, which is what makes
   the intersection do work: the widest closure is read first, so something has to be dropped from it.

   It also carries the two specifier shapes that are not edges. A bare specifier is a package, which the closure has
   no business resolving, and a relative specifier that resolves to nothing is a broken module the bundler will fail
   on rather than a sheet anything loads. */
import { useState } from "react";

import "./widget.css";
import "../shared/solo.css";
import "./gone.css";

export function Another() {
  return useState(0)[0];
}
