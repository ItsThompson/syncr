import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { filesUnder } from "../../lib/files.ts";
import { appSourceDir } from "../../lib/paths.ts";
import { checkUnsafeClientCalls } from "../unsafe-client-calls-check.ts";
import { policyForUnsafeClientCall } from "../unsafe-client-calls.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = (name: string): string => path.join(here, "..", "__fixtures__", name);

const check = async (names: string[]) => checkUnsafeClientCalls({ hookFiles: names.map(fixture) });

describe("unsafe client call policy", () => {
  it("classifies every unsafe client call in the api hooks", async () => {
    const hookFiles = (
      await filesUnder(path.join(appSourceDir, "api", "hooks"), [".ts", ".tsx"])
    ).filter((file) => !file.includes(".test."));

    const outcome = await checkUnsafeClientCalls({ hookFiles });

    expect(outcome.findings).toEqual([]);
  });

  it("refuses a guarded write after its idempotency header is deleted", async () => {
    const outcome = await check(["guarded-without-header.ts"]);

    expect(outcome.findings).toMatchObject([
      {
        check: "missing-idempotency-header",
        message: expect.stringContaining("POST /api/v1/weeks/{iso_week}/pins"),
      },
    ]);
  });

  it("refuses a new unsafe call before the policy classifies it", async () => {
    const outcome = await check(["unclassified-unsafe-call.ts"]);

    expect(outcome.findings).toMatchObject([
      {
        check: "unclassified-unsafe-client-call",
        message: expect.stringContaining("POST /api/v1/unclassified"),
      },
    ]);
  });

  it("names the route and reason for an exempt call", () => {
    expect(policyForUnsafeClientCall("POST", "/api/v1/weeks/{iso_week}/tradeoffs")).toEqual({
      method: "POST",
      route: "/api/v1/weeks/{iso_week}/tradeoffs",
      policy: { classification: "exempt", reason: "the route carries no guard" },
    });
  });
});
