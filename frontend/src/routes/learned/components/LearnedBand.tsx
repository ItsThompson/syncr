/* The screen's header band: the serif title, and how many parameters are still collecting.
 *
 * THE COUNT IS THE HEADER'S SUBJECT, which is `US-LEARN-01`'s own requirement. A reader opening this screen in
 * week two is asking whether anything is wrong, and the answer is a count of parameters still gathering
 * evidence: stating it in the band is what stops the table below reading as a list of failures.
 *
 * IT IS STATED AT INFORMATIONAL VOLUME AND IN THE BAND'S OWN INK. No amber, no oxide, no mark. Nothing is
 * broken while a parameter collects, and painting the count in a signal pigment would teach the reader to
 * distrust a working system, which is the one thing section 11 says this screen must not do.
 *
 * THE BAND RENDERS IN EVERY STATE, INCLUDING BEFORE THE READ ARRIVES. A screen's title is a fact about the
 * destination rather than about whether a response landed, so the counts are optional: absent is what "not yet
 * known" looks like, and zero is a count that renders as one. */

import { Plate } from "../../../ui/domain";

export interface LearnedBandProps {
  /** How many parameters are below their threshold. Absent until the read arrives. */
  readonly collecting?: number | undefined;
  /** How many the solver is applying. */
  readonly ready?: number | undefined;
  /** Which version is in force, and where it came from. */
  readonly version?: number | undefined;
  readonly origin?: string | undefined;
}

/** The eyebrow: what is still collecting, out of what exists. */
function counts(collecting: number | undefined, ready: number | undefined): string {
  if (collecting === undefined || ready === undefined) return "reading what has been learned";
  const total = collecting + ready;
  if (total === 0) return "no parameter has been fitted yet";
  return `${collecting} of ${total} ${total === 1 ? "parameter" : "parameters"} still collecting`;
}

/** Which weights are in force, which is the provenance every figure on this screen carries. */
function provenance(version: number | undefined, origin: string | undefined): string | null {
  if (version === undefined || origin === undefined) return null;
  return `Weight set ${version}, ${origin}.`;
}

export function LearnedBand({ collecting, ready, version, origin }: LearnedBandProps) {
  const inForce = provenance(version, origin);

  return (
    <section className="flex flex-wrap items-end gap-4 border-b border-rule-strong bg-paper-raised px-3.75 py-2.75">
      <div>
        <p className="text-eyebrow tracking-eyebrow uppercase text-text-muted">
          {counts(collecting, ready)}
        </p>
        <h1 className="font-serif text-title leading-tight text-ink-deep">Learned</h1>
      </div>
      <p className="text-eyebrow text-text-muted">
        What syncr has fitted from your own confirmed weeks, and what it is still gathering.
      </p>
      <div className="ml-auto flex items-center gap-3.25">
        {inForce === null ? null : <p className="text-eyebrow text-text-muted">{inForce}</p>}
        <Plate name="astrolabe" fit="band" />
      </div>
    </section>
  );
}
