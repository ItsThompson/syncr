/* The response fields the committed OpenAPI document declares.
 *
 * Read off the document rather than off the FastAPI app, because the document is what the client is
 * generated from: a field the app has and the document does not is a different question with a
 * different answer.
 *
 * Only schemas a response can answer with are read. A request body goes through the opposite
 * transform at the client boundary, so folding both into one figure would report a field about a
 * direction it never travels. */

const SCHEMA_REF_PREFIX = "#/components/schemas/";

/* The keys that decide a property's TYPE. A finding quotes these and drops the prose, because a
 * description runs to several sentences and says nothing about why the field went missing. */
const TYPE_KEYS = ["$ref", "type", "anyOf", "oneOf", "allOf", "enum", "const", "items"] as const;

export interface DeclaredField {
  /** The schema's name in `components/schemas`. */
  readonly schema: string;
  readonly property: string;
  /** The property's own subschema, type keys only, as the document spells it. */
  readonly declaredAs: string;
}

export interface DeclaredResponseFields {
  /** Every response-reachable schema that declares properties, in the order the closure reaches them. */
  readonly schemas: readonly string[];
  readonly fields: readonly DeclaredField[];
}

export function declaredResponseFields(documentText: string): DeclaredResponseFields {
  const document = requireRecord(JSON.parse(documentText) as unknown, "the document");
  const schemas = requireRecord(
    requireRecord(document.components, "components").schemas,
    "components/schemas",
  );

  const declaring = reachableFromAResponse(document, schemas);
  const fields: DeclaredField[] = [];
  for (const [name, properties] of declaring) {
    for (const [property, subschema] of Object.entries(properties)) {
      fields.push({ schema: name, property, declaredAs: spellType(subschema) });
    }
  }
  return { schemas: [...declaring.keys()], fields };
}

/**
 * Every schema a response can answer with, directly or through a `$ref` chain, that declares
 * properties, with the properties it declares.
 *
 * The closure is what makes the check whole-document rather than top-level: a nested model is only
 * ever reached through the field that refers to it.
 */
function reachableFromAResponse(
  document: Record<string, unknown>,
  schemas: Record<string, unknown>,
): ReadonlyMap<string, Record<string, unknown>> {
  const pending = responseBodies(document).flatMap(refsIn);
  const declaring = new Map<string, Record<string, unknown>>();
  const seen = new Set<string>();
  while (pending.length > 0) {
    const name = pending.pop();
    if (name === undefined || seen.has(name)) continue;
    seen.add(name);
    /* A schema that declares no properties is ordinary, and one a `$ref` names but the document does
     * not define is malformed. Separating them is what keeps a dangling reference from shrinking the
     * denominator instead of failing the check. */
    const schema = requireRecord(schemas[name], `components/schemas/${name}`);
    if (isRecord(schema.properties)) declaring.set(name, schema.properties);
    pending.push(...refsIn(schema));
  }
  return declaring;
}

function responseBodies(document: Record<string, unknown>): unknown[] {
  const bodies: unknown[] = [];
  for (const item of Object.values(requireRecord(document.paths, "paths"))) {
    if (!isRecord(item)) continue;
    for (const operation of Object.values(item)) {
      if (!isRecord(operation) || !isRecord(operation.responses)) continue;
      for (const response of Object.values(operation.responses)) {
        if (!isRecord(response) || !isRecord(response.content)) continue;
        for (const media of Object.values(response.content)) {
          if (isRecord(media) && "schema" in media) bodies.push(media.schema);
        }
      }
    }
  }
  return bodies;
}

function refsIn(node: unknown): string[] {
  if (Array.isArray(node)) return node.flatMap(refsIn);
  if (!isRecord(node)) return [];
  return Object.entries(node).flatMap(([key, value]) =>
    key === "$ref" && typeof value === "string" && value.startsWith(SCHEMA_REF_PREFIX)
      ? [value.slice(SCHEMA_REF_PREFIX.length)]
      : refsIn(value),
  );
}

function spellType(subschema: unknown): string {
  if (!isRecord(subschema)) return JSON.stringify(subschema);
  const spelled = Object.fromEntries(
    TYPE_KEYS.filter((key) => key in subschema).map((key) => [key, subschema[key]]),
  );
  return JSON.stringify(spelled);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/* A malformed document fails the check rather than emptying it: a scan that read nothing is
 * indistinguishable from a scan that found nothing. */
function requireRecord(value: unknown, what: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`the OpenAPI document has no ${what} object`);
  return value;
}
