/* The contract check's own verdict, against a fixture generated the way the tree's own contract is.
 *
 * `__fixtures__/planted/schema.d.ts` was produced by running the repository's own `codegen` over
 * `__fixtures__/planted/openapi.json`, so the fixture is not a hand-written imitation of what
 * `openapi-typescript` emits: it is what it emits. The planted document declares the shape this check
 * exists to catch, a field typed exactly `null`, beside the four shapes that look like it and survive.
 *
 * The negative cases carry the weight. A check that reported `null[]` or a nullable `$ref` would fail
 * on a contract that is correct, and a check that reported a request body would name a field about a
 * direction it never travels. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { CheckOutcome } from "../../lib/findings.ts";
import { generatedSchema, openapiDocument, tsconfig } from "../../lib/paths.ts";
import { checkContract } from "../check.ts";
import { propertiesReachingClient } from "../client.ts";
import { declaredResponseFields } from "../document.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const plantedDocument = path.join(here, "..", "__fixtures__", "planted", "openapi.json");
const plantedSchema = path.join(here, "..", "__fixtures__", "planted", "schema.d.ts");

async function verdictFor(document: string, schema: string): Promise<CheckOutcome> {
  const declared = declaredResponseFields(await readFile(document, "utf8"));
  return checkContract({
    documentPath: document,
    generatedSchemaPath: schema,
    declared,
    answer: propertiesReachingClient({
      generatedSchema: schema,
      tsconfig,
      schemas: declared.schemas,
    }),
  });
}

const plantedVerdict = await verdictFor(plantedDocument, plantedSchema);

function absences(outcome: CheckOutcome): string[] {
  return outcome.findings
    .filter((finding) => finding.check === "field-absent-from-the-generated-client")
    .map((finding) => finding.message);
}

describe("a field typed exactly null", () => {
  it("is reported on the schema a response answers with, and named with its declared type", () => {
    const reported = absences(plantedVerdict).filter((message) =>
      message.startsWith("PlantedResponse.placeholder"),
    );

    expect(reported).toHaveLength(1);
    expect(reported[0]).toContain('{"type":"null"}');
    expect(reported[0]).toContain("absent from what the client answers with");
  });

  it("is reported when the document spells it as an enumeration of null", () => {
    const reported = absences(plantedVerdict).filter((message) =>
      message.startsWith("PlantedResponse.enumeratedNull"),
    );

    expect(reported).toHaveLength(1);
    expect(reported[0]).toContain('{"enum":[null]}');
  });

  it("is reported inside a schema reached only through a $ref, which a top-level scan would miss", () => {
    expect(
      absences(plantedVerdict).filter((m) => m.startsWith("NestedResponse.buried")),
    ).toHaveLength(1);
  });

  it("is not reported on a request body, which travels the other way", () => {
    expect(absences(plantedVerdict).join("\n")).not.toContain("PlantedRequest");
  });

  it("is the only thing reported: the planted document has exactly three", () => {
    expect(absences(plantedVerdict)).toHaveLength(3);
    expect(plantedVerdict.findings).toHaveLength(3);
  });
});

describe("a field that survives the response mapping", () => {
  it.each([
    ["kept", "a plain string"],
    ["arrayOfNull", "an array of nothing, which is still an array"],
    ["nullableObject", "a nullable $ref"],
    ["nested", "a $ref"],
    ["held", "a number inside the nested schema"],
  ])("%s is not reported: %s", (property) => {
    expect(absences(plantedVerdict).join("\n")).not.toContain(`.${property} `);
  });
});

describe("the committed contract", () => {
  it("answers with every field it declares on a response", async () => {
    const outcome = await verdictFor(openapiDocument, generatedSchema);

    expect(outcome.findings).toEqual([]);
    expect(outcome.notes.join("\n")).toContain("reach the generated client");
  });
});

describe("a measurement that did not happen", () => {
  it("refuses rather than passes when the generated types cannot be resolved", async () => {
    const outcome = await verdictFor(plantedDocument, path.join(here, "..", "absent.d.ts"));

    expect(outcome.findings.length).toBeGreaterThan(0);
    expect(outcome.findings.every((finding) => finding.check === "contract-not-measured")).toBe(
      true,
    );
    expect(outcome.findings[0]?.message).toContain("asserted nothing");
  });

  it("refuses rather than passes when no response declares a property", () => {
    const document = JSON.stringify({
      paths: { "/nothing": { get: { responses: { "204": { description: "no content" } } } } },
      components: { schemas: {} },
    });

    const outcome = checkContract({
      documentPath: plantedDocument,
      generatedSchemaPath: plantedSchema,
      declared: declaredResponseFields(document),
      answer: { reaching: new Map(), refusals: [] },
    });

    expect(outcome.findings).toHaveLength(1);
    expect(outcome.findings[0]?.check).toBe("contract-not-measured");
  });

  it("refuses a response body pointing at a schema the document does not define", () => {
    const document = JSON.stringify({
      paths: {
        "/dangling": {
          get: {
            responses: {
              "200": {
                content: {
                  "application/json": { schema: { $ref: "#/components/schemas/Absent" } },
                },
              },
            },
          },
        },
      },
      components: { schemas: {} },
    });

    expect(() => declaredResponseFields(document)).toThrow(/components\/schemas\/Absent/);
  });

  it("reports a schema the client answered with no type for once, not once per property", async () => {
    const declared = declaredResponseFields(await readFile(plantedDocument, "utf8"));

    const outcome = checkContract({
      documentPath: plantedDocument,
      generatedSchemaPath: plantedSchema,
      declared,
      answer: { reaching: new Map(), refusals: [] },
    });

    expect(declared.schemas).toEqual(["PlantedResponse", "NestedResponse"]);
    expect(outcome.findings).toHaveLength(2);
    expect(
      outcome.findings.every(
        (finding) => finding.check === "schema-absent-from-the-generated-client",
      ),
    ).toBe(true);
  });

  it("refuses a document with no schemas object rather than reading it as empty", () => {
    expect(() => declaredResponseFields(JSON.stringify({ paths: {} }))).toThrow(/components/);
  });
});
