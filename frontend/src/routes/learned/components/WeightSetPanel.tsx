/* The versions, their origin, which one is in force, and the one action that changes that.
 *
 * ACTIVATING AND REVERTING ARE THE SAME ACTION, so there is one control and one label. Putting version 1 back in
 * force is activating version 1: a separate revert would be a second name for one flip, and a reader deciding
 * which of two buttons undoes a bad fit is a reader who has been given a puzzle. `US-LEARN-07`.
 *
 * NO REPROCESSING OF HISTORY, AND THE PANEL SAYS SO. The flip re-solves future weeks only, because a past week's
 * approved revision keeps the inputs it was computed with. A reader who thinks a revert rewrites last month will
 * not use it.
 *
 * P0'S HAND-TUNED WEIGHTS COME THROUGH THIS MECHANISM, and the panel states that too. It is why the table has a
 * row at all before anything has been fitted, and it is the claim that makes the fitted path credible: the
 * versioning is not scaffolding waiting for a model, it is what is in force today.
 *
 * THAT SENTENCE IS ABOUT THE MECHANISM, NOT ABOUT THE ACTIVE ROW. "The weights in force were tuned by hand" read
 * off a screen with a FITTED set in force is the panel stating something false, which is what the first wording
 * did: a run against a real account with two versions showed it.
 *
 * THOSE TWO SENTENCES ARE THE CLIENT'S. Every figure and every claim ABOUT A PARAMETER is served, because two
 * surfaces must not describe one fitted number two ways. These two are fixed statements about the mechanism, with
 * no figure in them and no second renderer: the CLI has no weight-set command, so serving them would make a
 * static paragraph a request. The same reasoning the signal-source table states.
 *
 * THE ACTIVE ROW HAS NO CONTROL. Activating the version already in force is a no-op flip plus a re-solve, which
 * the api accepts on purpose, but a control offering it here would read as "apply", and this screen has nothing
 * to apply.
 *
 * ONE ACTIVATION AT A TIME, AND THE LOCK IS A REF. An activation re-solves every future week, which is the most
 * expensive act on this screen, and two clicks of an ordinary double-tap would ask for two waves of it. The api
 * is safe either way -- one version is active by a partial unique index, so the outcome is last-writer-wins
 * rather than no active set -- so what the lock saves is the work, not the data. It is a ref as well as a
 * disabled attribute because `disabled` reaches the DOM on the next render, and nothing guarantees a render
 * commits between the two clicks of a double-tap; the capture host states the same pair for the same reason.
 *
 * EVERY ROW'S CONTROL IS DISABLED WHILE ONE IS OUTSTANDING, not just the row pressed. A tenant has one set in
 * force, so a second version pressed while the first is in flight is the same race rather than a second one. */

import { useRef, useState } from "react";

import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { Table, type TableColumn } from "../../../ui/domain";
import { ReadFailure } from "../../templates/components/ReadFailure";
import type { ActivationBody, WeightSet, WeightSets } from "../../../api/hooks/useLearned";
import type { Write } from "../../../api/hooks/useWrite";

export interface WeightSetPanelProps {
  readonly versions: WeightSets;
  readonly activate: Write<ActivationBody>;
}

/** U+2014 EM DASH, which is how every table in this product spells a cell with nothing in it. */
const NOTHING = "\u2014";

function fittedAt(version: WeightSet): string {
  return version.fittedAt === null ? NOTHING : version.fittedAt.slice(0, 10);
}

function columns(
  putInForce: (version: number) => void,
  isSending: boolean,
): readonly TableColumn<WeightSet>[] {
  return [
    { key: "version", header: "Version", measure: "figure", cell: (row) => String(row.version) },
    { key: "origin", header: "Origin", cell: (row) => row.origin },
    { key: "fitted", header: "Fitted", cell: (row) => fittedAt(row) },
    { key: "ready", header: "Ready", measure: "figure", cell: (row) => String(row.ready) },
    {
      key: "collecting",
      header: "Collecting",
      measure: "figure",
      cell: (row) => String(row.collecting),
    },
    {
      key: "state",
      header: "In force",
      cell: (row) =>
        row.active ? (
          <span className="text-eyebrow tracking-eyebrow uppercase text-text-muted">in force</span>
        ) : (
          <Button
            rank="secondary"
            size="sm"
            isDisabled={isSending}
            onClick={() => putInForce(row.version)}
          >
            Put in force
          </Button>
        ),
    },
  ];
}

export function WeightSetPanel({ versions, activate }: WeightSetPanelProps) {
  /* The request, which outlives the press that started it. `isSending` is what disables the controls and the ref
   * is the same fact answerable inside a click handler, where the state is one render too late. Both move in
   * `putInForce` and nowhere else, so they cannot drift apart. */
  const [isSending, setSending] = useState(false);
  const inFlight = useRef(false);

  const putInForce = (version: number) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    /* Released in a `finally` rather than after the answer, so the lock cannot outlive the request. `submit`
     * ANSWERS a refusal rather than throwing one, so a `then` would release it too today: the `finally` is what
     * keeps that true if the write path ever rejects, and releasing only on success is the version the refusal
     * case reddens. */
    void activate.submit({ version }).finally(() => {
      inFlight.current = false;
      setSending(false);
    });
  };

  return (
    <Panel title="Weight sets">
      <div className="flex flex-col gap-2.75">
        <Table
          caption="Every weight set version, its origin, and which one is in force"
          columns={columns(putInForce, isSending)}
          rows={versions.versions}
          rowKey={(row) => String(row.version)}
          countLabel={(count) => `${count} ${count === 1 ? "version" : "versions"}`}
        />
        <p className="text-base text-ink">
          Putting a version in force is one action, and it is the same action a rollback is: no
          history is reprocessed, and only weeks from this one on are solved again. A week you have
          already approved keeps the plan it was approved with.
        </p>
        <p className="text-base text-ink-soft">
          The weights syncr ships are tuned by hand, and they arrive through this same mechanism a
          fitted set does: a row, a version, and a flag. Nothing switches over when fitting starts.
        </p>
        {activate.problem === null ? null : (
          <ReadFailure title="That version was not put in force" problem={activate.problem} />
        )}
      </div>
    </Panel>
  );
}
