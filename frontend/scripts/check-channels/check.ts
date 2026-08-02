/* Asserting that each state channel is assigned in exactly one file under the kit.
 *
 * It passes trivially now, with one file assigning three pairs. That is the point: it is the
 * mechanism that keeps passing as the kit grows, and the first duplicate assignment fails a gate
 * rather than reaching a review that has to notice it by eye. */

import { readFile } from "node:fs/promises";

import { classStringsIn } from "../lib/class-strings.ts";
import { codeWithoutComments, createPositionResolver } from "../lib/css-scan.ts";
import { parseCustomVariants } from "../lib/custom-variants.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { relativeToRepo } from "../lib/paths.ts";
import { PSEUDO_STATES, channelFor, channelForUtility } from "./channels.ts";

export interface CheckChannelsInput {
  /** Absolute paths of the kit's CSS and TSX files. */
  readonly kitFiles: readonly string[];
  /** Absolute path of `theme.css`, which maps each variant name onto its state selector. */
  readonly themeFile: string;
}

interface Assignment {
  readonly state: string;
  readonly channel: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
}

const RULE = /([^{}]+)\{([^{}]*)\}/g;

/** Maps a variant name onto the state selector it stands for, read from the theme. */
export function variantStates(themeSource: string): Map<string, string> {
  const states = new Map<string, string>();
  for (const variant of parseCustomVariants(themeSource)) {
    if (variant.attribute !== undefined) states.set(variant.name, variant.attribute);
  }
  for (const pseudo of PSEUDO_STATES) {
    states.set(pseudo.replace(/^[:]/, ""), pseudo);
  }
  return states;
}

function statesInSelector(selector: string): string[] {
  const found = new Set<string>();
  for (const attribute of selector.match(/data-[a-z][a-z0-9-]*/g) ?? []) found.add(attribute);
  for (const pseudo of PSEUDO_STATES) {
    if (pseudo.startsWith(":") && selector.includes(pseudo)) found.add(pseudo);
  }
  return [...found];
}

function assignmentsInCss(file: string, source: string): Assignment[] {
  const at = createPositionResolver(source);
  const code = codeWithoutComments(source);
  const assignments: Assignment[] = [];

  for (const rule of code.matchAll(RULE)) {
    const states = statesInSelector(rule[1]);
    if (states.length === 0) continue;

    let offset = rule.index + rule[1].length + 1;
    for (const statement of rule[2].split(";")) {
      const property = statement.split(":")[0].trim();
      const channel = channelFor(property);
      if (channel !== null) {
        const position = at(offset + (statement.length - statement.trimStart().length));
        for (const state of states) assignments.push({ state, channel, file, ...position });
      }
      offset += statement.length + 1;
    }
  }
  return assignments;
}

function assignmentsInMarkup(
  file: string,
  source: string,
  states: ReadonlyMap<string, string>,
): Assignment[] {
  const assignments: Assignment[] = [];

  for (const classString of classStringsIn(source)) {
    for (const token of classString.text.split(/\s+/).filter((part) => part !== "")) {
      const segments = token.split(":");
      const utility = segments[segments.length - 1];
      const channel = channelForUtility(utility);
      if (channel === null) continue;
      for (const variant of segments.slice(0, -1)) {
        const state = states.get(variant);
        if (state === undefined) continue;
        assignments.push({
          state,
          channel,
          file,
          line: classString.line,
          column: classString.column,
        });
      }
    }
  }
  return assignments;
}

export async function checkChannels(input: CheckChannelsInput): Promise<CheckOutcome> {
  const states = variantStates(await readFile(input.themeFile, "utf8"));
  const assignments: Assignment[] = [];

  for (const file of input.kitFiles) {
    const source = await readFile(file, "utf8");
    if (file.endsWith(".css")) assignments.push(...assignmentsInCss(file, source));
    else assignments.push(...assignmentsInMarkup(file, source, states));
  }

  const byPair = new Map<string, Assignment[]>();
  for (const assignment of assignments) {
    const key = `${assignment.state} -> ${assignment.channel}`;
    byPair.set(key, [...(byPair.get(key) ?? []), assignment]);
  }

  const findings: Finding[] = [];
  for (const [pair, claims] of byPair) {
    const files = [...new Set(claims.map((claim) => claim.file))];
    if (files.length < 2) continue;
    /* Located at the first claim from a file OTHER than the one seen first, so the position points at
     * the assignment that arrived second rather than at the file that was already there. */
    const offender = claims.find((claim) => claim.file !== files[0]) ?? claims[0];
    findings.push({
      file: offender.file,
      line: offender.line,
      column: offender.column,
      check: "one-file-per-channel",
      message:
        `${pair} is assigned in ${files.length} files: ${files.map(relativeToRepo).join(", ")}. ` +
        "Two definitions of one state's channel drift apart, and nothing on a rendered screen " +
        "shows the disagreement until the states co-occur.",
    });
  }

  return {
    findings,
    notes: [
      `${input.kitFiles.length} kit file(s), ${byPair.size} state channel(s) assigned`,
      ...[...byPair.keys()].toSorted().map((pair) => `  ${pair}`),
    ],
  };
}
