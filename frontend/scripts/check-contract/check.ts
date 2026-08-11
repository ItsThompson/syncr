/* The document's declared response fields, crossed against the fields the generated client answers
 * with.
 *
 * The comparison is one way on purpose. A field the client carries and the document does not cannot
 * exist, because the client's types are generated from the document; a field the document carries and
 * the client drops is invisible from either file alone, which is why it needs a check. */

import { abbreviate, type CheckOutcome, type Finding } from "../lib/findings.ts";
import type { ClientAnswer } from "./client.ts";
import type { DeclaredResponseFields } from "./document.ts";

const ADVICE =
  "A field typed exactly `null` does not survive the client's response mapping, so type it as its " +
  "eventual shape or as a nullable object.";

export interface CheckContractInput {
  /** Absolute path of the committed OpenAPI document, for a finding a reader can open. */
  readonly documentPath: string;
  /** Absolute path of the committed generated types. */
  readonly generatedSchemaPath: string;
  readonly declared: DeclaredResponseFields;
  readonly answer: ClientAnswer;
}

export function checkContract(input: CheckContractInput): CheckOutcome {
  const { declared, answer } = input;

  if (answer.refusals.length > 0) {
    return {
      findings: answer.refusals.map((refusal) => ({
        file: input.generatedSchemaPath,
        check: "contract-not-measured",
        message: `${refusal}. The types the client answers with were never resolved, so this check asserted nothing.`,
      })),
      notes: [`${declared.fields.length} declared field(s) read from the document`],
    };
  }

  const findings: Finding[] = [];
  if (declared.fields.length === 0) {
    findings.push({
      file: input.documentPath,
      check: "contract-not-measured",
      message:
        "no response schema in the document declares a property, so this check examined nothing.",
    });
  }

  let reachingCount = 0;
  for (const field of declared.fields) {
    const reaching = answer.reaching.get(field.schema);
    if (reaching === undefined) {
      findings.push({
        file: input.generatedSchemaPath,
        check: "schema-absent-from-the-generated-client",
        message: `${field.schema} is declared in the document and the client answers with no type for it at all.`,
      });
      continue;
    }
    if (reaching.has(field.property)) {
      reachingCount += 1;
      continue;
    }
    findings.push({
      file: input.documentPath,
      check: "field-absent-from-the-generated-client",
      message:
        `${field.schema}.${field.property} is declared as ${abbreviate(field.declaredAs, 72)} ` +
        `and is absent from what the client answers with, so no caller can read it. ${ADVICE}`,
    });
  }

  return {
    findings,
    notes: [
      `${declared.schemas.length} response schema(s) reached from the document's own responses`,
      `${reachingCount} of ${declared.fields.length} declared field(s) reach the generated client`,
      "resolved by the compiler against openapi-fetch's own response type, not by a rule restated here",
    ],
  };
}
