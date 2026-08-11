/* WHAT A BARREL'S SIDE EFFECTS COST, AS A FIGURE THE BUILD PRODUCES.
 *
 * `ui/domain/index.ts` and `ui/primitives/index.ts` each re-export a whole layer, and every component in that
 * layer imports its own stylesheet for the side effect. So one named import loads the layer's sheets, and what
 * that costs is a number. A number written into a comment drifts from the artifact the day after it is written,
 * so each barrel is compiled twice: once through the barrel, once from the component's own module. The
 * difference is what going through the barrel loads.
 *
 * The component is named rather than derived, so a reader reproduces the figure by writing the same import. */

import path from "node:path";

import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { asKb } from "../lib/bytes.ts";
import { frontendRoot, relativeToRepo } from "../lib/paths.ts";

function kitModule(...segments: readonly string[]): string {
  return path.join(frontendRoot, "src", "ui", ...segments);
}

export interface BarrelProbe {
  /** The barrel, absolute, so a finding names a file a reader can open. */
  readonly barrel: string;
  /** The export imported through the barrel and again on its own. */
  readonly component: string;
  /** The module that component lives in, absolute. */
  readonly module: string;
}

export const BARREL_PROBES: readonly BarrelProbe[] = [
  {
    barrel: kitModule("domain", "index.ts"),
    component: "Table",
    module: kitModule("domain", "table", "index.ts"),
  },
  {
    barrel: kitModule("primitives", "index.ts"),
    component: "Button",
    module: kitModule("primitives", "Button.tsx"),
  },
];

/** One component's import, built both ways. */
export interface BarrelPayload {
  readonly probe: BarrelProbe;
  /** Bytes of CSS the build emitted for the import through the barrel. */
  readonly throughBarrelBytes: number;
  /** Bytes of CSS the build emitted for the same import from the component's own module. */
  readonly onItsOwnBytes: number;
}

export function checkBarrelPayloads(payloads: readonly BarrelPayload[]): CheckOutcome {
  const findings: Finding[] = [];
  const notes: string[] = [
    `${payloads.length} barrel(s) built twice, through the barrel and from the component's own module`,
  ];

  for (const { probe, throughBarrelBytes, onItsOwnBytes } of payloads) {
    notes.push(
      `  ${relativeToRepo(probe.barrel)}: ${probe.component} through the barrel emits ` +
        `${asKb(throughBarrelBytes)} of CSS, against ${asKb(onItsOwnBytes)} from ` +
        `${relativeToRepo(probe.module)}, so the barrel loads ${asKb(throughBarrelBytes - onItsOwnBytes)} ` +
        "the component's own module does not",
    );

    if (throughBarrelBytes === 0 || onItsOwnBytes === 0) {
      findings.push({
        file: probe.barrel,
        check: "barrel-payload-unmeasured",
        message:
          `one of the two builds of ${probe.component} emitted no stylesheet, so the figure beside it ` +
          "prices nothing. A build that reaches none of the layer's sheets is a probe that stopped " +
          "resolving, not a layer with nothing to load.",
      });
      continue;
    }

    if (throughBarrelBytes <= onItsOwnBytes) {
      findings.push({
        file: probe.barrel,
        check: "barrel-loads-no-more-than-the-component",
        message:
          `${probe.component} through the barrel emits ${asKb(throughBarrelBytes)} of CSS and ` +
          `${asKb(onItsOwnBytes)} from its own module, so the barrel loads nothing extra. This barrel ` +
          "states that importing one component may load another's stylesheet, and the artifact no longer " +
          "agrees: the statement is what has to change.",
      });
    }
  }

  return { findings, notes };
}
