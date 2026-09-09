/* Checks that every mutating api call carries the retry policy assigned to its route. */

import { readFile } from "node:fs/promises";

import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { policyForUnsafeClientCall, type UnsafeClientMethod } from "./unsafe-client-calls.ts";

export interface CheckUnsafeClientCallsInput {
  /** Absolute paths of the api hooks to scan. */
  readonly hookFiles: readonly string[];
}

interface UnsafeClientCall {
  readonly method: UnsafeClientMethod;
  readonly route: string | null;
  readonly source: string;
  readonly index: number;
}

const UNSAFE_CLIENT_METHOD =
  /client\.(POST|PUT|PATCH|DELETE)\s*\(\s*(?:"([^"]+)"|'([^']+)'|`([^`]+)`|([^,\s)]+))/g;
const IDEMPOTENCY_HEADERS = /\bheaders\s*:\s*idempotentHeaders\s*\(\s*\)/;

function endOfCall(source: string, start: number): number {
  const open = source.indexOf("(", start);
  let depth = 0;
  let quote: string | null = null;

  for (let index = open; index < source.length; index += 1) {
    const character = source[index];
    if (quote !== null) {
      if (character === "\\") {
        index += 1;
        continue;
      }
      if (character === quote) quote = null;
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      quote = character;
      continue;
    }
    if (character === "(") depth += 1;
    if (character !== ")") continue;
    depth -= 1;
    if (depth === 0) return index + 1;
  }

  return source.length;
}

function unsafeCallsIn(source: string): UnsafeClientCall[] {
  const calls: UnsafeClientCall[] = [];
  const code = blankJsComments(source);

  for (const match of code.matchAll(UNSAFE_CLIENT_METHOD)) {
    const method = match[1] as UnsafeClientMethod;
    const route = match[2] ?? match[3] ?? match[4] ?? null;
    calls.push({
      method,
      route,
      source: code.slice(match.index, endOfCall(code, match.index)),
      index: match.index,
    });
  }

  return calls;
}

function missingClassification(
  call: UnsafeClientCall,
  file: string,
  at: (index: number) => { line: number; column: number },
): Finding {
  return {
    file,
    ...at(call.index),
    check: "unclassified-unsafe-client-call",
    message:
      call.route === null
        ? `${call.method} receives a dynamic route, so no policy can classify it. Use a literal route.`
        : `${call.method} ${call.route} has no retry policy. Add a guarded or exempt policy entry before sending it.`,
  };
}

export async function checkUnsafeClientCalls(
  input: CheckUnsafeClientCallsInput,
): Promise<CheckOutcome> {
  const findings: Finding[] = [];
  let callCount = 0;
  let guardedCount = 0;
  let exemptCount = 0;

  for (const file of input.hookFiles) {
    const source = await readFile(file, "utf8");
    const at = createPositionResolver(source);
    for (const call of unsafeCallsIn(source)) {
      callCount += 1;
      if (call.route === null) {
        findings.push(missingClassification(call, file, at));
        continue;
      }

      const policy = policyForUnsafeClientCall(call.method, call.route);
      if (policy === undefined) {
        findings.push(missingClassification(call, file, at));
        continue;
      }

      const sendsIdempotencyHeaders = IDEMPOTENCY_HEADERS.test(call.source);
      if (policy.policy.classification === "guarded") {
        guardedCount += 1;
        if (!sendsIdempotencyHeaders) {
          findings.push({
            file,
            ...at(call.index),
            check: "missing-idempotency-header",
            message: `${call.method} ${call.route} is guarded but does not send idempotentHeaders().`,
          });
        }
        continue;
      }

      exemptCount += 1;
      if (sendsIdempotencyHeaders) {
        findings.push({
          file,
          ...at(call.index),
          check: "idempotency-header-on-exempt-route",
          message: `${call.method} ${call.route} is exempt: ${policy.policy.reason}.`,
        });
      }
    }
  }

  return {
    findings,
    notes: [
      `${input.hookFiles.length} api hook file(s), ${callCount} unsafe client call(s) classified`,
      `${guardedCount} guarded call(s), ${exemptCount} exempt because their route carries no guard`,
    ],
  };
}
