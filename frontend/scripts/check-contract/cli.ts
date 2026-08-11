#!/usr/bin/env node
/* Every field the document declares on a response, crossed against the fields the generated client
 * hands back. Runs in the pre-commit hook and in CI.
 *
 * It reads the two committed generated files and writes neither, starts no browser, and needs no api:
 * the whole question is answered by the compiler against files already in the tree. */

import { readFile } from "node:fs/promises";

import { generatedSchema, openapiDocument, tsconfig } from "../lib/paths.ts";
import { reportOutcome } from "../lib/report.ts";
import { checkContract } from "./check.ts";
import { propertiesReachingClient } from "./client.ts";
import { declaredResponseFields } from "./document.ts";

const declared = declaredResponseFields(await readFile(openapiDocument, "utf8"));

const outcome = checkContract({
  documentPath: openapiDocument,
  generatedSchemaPath: generatedSchema,
  declared,
  answer: propertiesReachingClient({
    generatedSchema,
    tsconfig,
    schemas: declared.schemas,
  }),
});

process.exit(reportOutcome("generated contract", outcome));
