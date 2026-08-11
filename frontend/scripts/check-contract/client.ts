/* WHAT THE GENERATED CLIENT ANSWERS WITH, ASKED OF THE COMPILER RATHER THAN OF A RULE WRITTEN HERE.
 *
 * The document declares a field; `schema.d.ts` carries it; and the client may still not hand it back,
 * because `openapi-fetch` maps a response body through `Readable<T>` before it becomes `data`. That
 * mapping drops any key whose type is exactly `null`: it keeps a key when
 * `NonNullable<T[K]> extends $Write<any>` is false, `NonNullable<null>` is `never`, and `never`
 * extends everything. An array of nothing is still an array, so `null[]` survives and `null` does not.
 *
 * So the oracle is the client's own response type, resolved by `typescript` against the committed
 * `schema.d.ts` and `openapi-fetch`'s own `FetchResponse`. Restating the dropping rule here instead
 * would be a check that certifies its own reading: it would keep passing after the transform it
 * describes had changed.
 *
 * The probe module exists in memory only. Nothing under `src/` imports it and neither generated file
 * is written. */

import path from "node:path";

import ts from "typescript";

const PROBE_BASENAME = "response-fields.probe.ts";
const ALIAS_PREFIX = "Reaches_";
const ALIAS = new RegExp(`^${ALIAS_PREFIX}(\\d+)$`);

export interface ClientAnswerInput {
  /** Absolute path of the committed `schema.d.ts`. */
  readonly generatedSchema: string;
  /** Absolute path of the tsconfig whose options the application itself is compiled with. */
  readonly tsconfig: string;
  /** Schema names to resolve, in the order the answer is keyed by. */
  readonly schemas: readonly string[];
}

export interface ClientAnswer {
  /** Per schema name, the properties the client's response type carries. */
  readonly reaching: ReadonlyMap<string, ReadonlySet<string>>;
  /** Why a measurement did not happen. Non-empty means the answer above is not evidence. */
  readonly refusals: readonly string[];
}

export function propertiesReachingClient(input: ClientAnswerInput): ClientAnswer {
  const probe = path.join(path.dirname(input.generatedSchema), PROBE_BASENAME);
  const text = probeText(input.schemas, input.generatedSchema);

  const configured = compilerOptions(input.tsconfig);
  if (configured.refusals.length > 0) return { reaching: new Map(), refusals: configured.refusals };

  const program = ts.createProgram(
    [probe],
    configured.options,
    hostServing(probe, text, configured.options),
  );
  const source = program.getSourceFile(probe);
  if (source === undefined) {
    return { reaching: new Map(), refusals: ["the probe module did not enter the program"] };
  }

  const complaints = [
    ...program.getSyntacticDiagnostics(source),
    ...program.getSemanticDiagnostics(source),
  ].map((diagnostic) => ts.flattenDiagnosticMessageText(diagnostic.messageText, " "));
  if (complaints.length > 0) return { reaching: new Map(), refusals: complaints };

  const checker = program.getTypeChecker();
  const reaching = new Map<string, ReadonlySet<string>>();
  for (const statement of source.statements) {
    if (!ts.isTypeAliasDeclaration(statement)) continue;
    const schema = schemaOf(statement.name.text, input.schemas);
    if (schema === null) continue;
    reaching.set(schema, propertyNames(checker, checker.getTypeAtLocation(statement.name)));
  }
  return { reaching, refusals: [] };
}

/**
 * The client's response type for a body of `T`, expressed through `openapi-fetch`'s own
 * `FetchResponse` so the transform is the library's rather than this file's.
 *
 * `["data"]` reads the field off both arms of the union, which is the body on the success arm and
 * `undefined` on the refusal arm, and `NonNullable` takes the body.
 */
function probeText(schemas: readonly string[], generatedSchema: string): string {
  const specifier = `./${path.basename(generatedSchema).replace(/\.d\.ts$|\.ts$/, "")}`;
  return [
    `import type { FetchResponse } from "openapi-fetch";`,
    `import type { components } from "${specifier}";`,
    ``,
    `type Body<T> = { responses: { 200: { content: { "application/json": T } } } };`,
    `type Answered<T> = NonNullable<FetchResponse<Body<T>, object, "application/json">["data"]>;`,
    ``,
    ...schemas.map(
      (schema, index) =>
        `export type ${ALIAS_PREFIX}${index} = Answered<components["schemas"][${JSON.stringify(schema)}]>;`,
    ),
    ``,
  ].join("\n");
}

/** A union answers with a field when any arm does, so the arms are read together. */
function propertyNames(checker: ts.TypeChecker, type: ts.Type): ReadonlySet<string> {
  if (type.isUnion()) {
    return new Set(type.types.flatMap((arm) => [...propertyNames(checker, arm)]));
  }
  return new Set(checker.getPropertiesOfType(type).map((property) => property.name));
}

function schemaOf(aliasName: string, schemas: readonly string[]): string | null {
  const matched = ALIAS.exec(aliasName);
  if (matched === null) return null;
  const index = Number(matched[1]);
  return index in schemas ? schemas[index] : null;
}

/* The application's own options, so the check reads the types the application reads rather than a
 * second dialect of them: `exactOptionalPropertyTypes` and `strict` both change what a property is. */
function compilerOptions(tsconfig: string): {
  readonly options: ts.CompilerOptions;
  readonly refusals: readonly string[];
} {
  const read = ts.readConfigFile(tsconfig, (file) => ts.sys.readFile(file));
  if (read.error !== undefined) {
    return {
      options: {},
      refusals: [ts.flattenDiagnosticMessageText(read.error.messageText, " ")],
    };
  }
  const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, path.dirname(tsconfig));
  return {
    options: { ...parsed.options, noEmit: true },
    refusals: parsed.errors.map((error) => ts.flattenDiagnosticMessageText(error.messageText, " ")),
  };
}

function hostServing(probe: string, text: string, options: ts.CompilerOptions): ts.CompilerHost {
  const host = ts.createCompilerHost(options, true);
  const { fileExists, getSourceFile, readFile } = host;
  return {
    ...host,
    fileExists: (file) => file === probe || fileExists.call(host, file),
    readFile: (file) => (file === probe ? text : readFile.call(host, file)),
    getSourceFile: (file, languageVersion, onError, shouldCreate) =>
      file === probe
        ? ts.createSourceFile(probe, text, languageVersion, true)
        : getSourceFile.call(host, file, languageVersion, onError, shouldCreate),
  };
}
