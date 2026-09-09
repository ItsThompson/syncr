import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import { areaHues, pigmentFile } from "../../../../../scripts/validate-tokens/hues.ts";
import { designSheetDir } from "../../../../../scripts/lib/paths.ts";

type PigmentOverrides = Readonly<Record<string, string>>;

async function sheetText(): Promise<string> {
  return readFile(path.join(designSheetDir, "specimen.html"), "utf8");
}

async function areaTokenValues(overrides: PigmentOverrides): Promise<Map<string, string>> {
  const pigments = areaHues(await readFile(pigmentFile, "utf8"));
  return new Map(
    pigments.map((pigment) => [`--area-${pigment.id}`, overrides[pigment.id] ?? pigment.hex]),
  );
}

async function renderedTightPairs(overrides: PigmentOverrides = {}): Promise<string> {
  const parsed = new DOMParser().parseFromString(await sheetText(), "text/html");
  document.documentElement.innerHTML = parsed.documentElement.innerHTML;

  const tokenValues = await areaTokenValues(overrides);
  vi.stubGlobal("getComputedStyle", () => ({
    getPropertyValue: (name: string) => tokenValues.get(name) ?? "",
  }));

  try {
    const script = [...document.querySelectorAll("script")]
      .map((element) => element.textContent)
      .join("\n");
    new Function(script)();
    return document.querySelector("#tight-pairs")?.textContent ?? "";
  } finally {
    vi.unstubAllGlobals();
  }
}

describe("the specimen's Area ramp", () => {
  it("derives its tightest pairs from the linked Area tokens at load", async () => {
    const shipped = await renderedTightPairs();
    const retuned = await renderedTightPairs({ "03": "#0000ff" });

    expect(shipped).toContain("all four of the tightest pairs carry different patterns");
    expect(retuned).not.toBe(shipped);
  });
});
