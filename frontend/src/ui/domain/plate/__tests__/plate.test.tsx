/* THE PLATES, AND THE PROVENANCE THAT HAS TO TRAVEL WITH THEM.
 *
 * Illustration is generated rather than licensed per asset, and this is the pairing that makes the claim
 * auditable: every plate the application can render has a manifest entry naming its source and licence, and every
 * entry has a committed file. Both directions matter. A plate with no entry is one nobody can clear, and an entry
 * with no plate is a record of something that is not here.
 *
 * NEVER BEHIND DATA is asserted structurally rather than by eye: the plate is an `img` in the flow, and the
 * stylesheet declares no `position`, no `z-index` and no `background-image`, so there is no way to put one under
 * the week grid, the Today ledger or a chart. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { srcDir } from "../../../../testing/compileTheme";
import { domainDir, kitStylesheet } from "../../../../testing/kitStylesheets";
import { Plate } from "../Plate";
import { PLATES, type PlateName } from "../plates";

const plateDir = path.join(srcDir, "assets", "plates");

interface ManifestRecord {
  readonly id: string;
  readonly subject: string;
  readonly source: string;
  readonly licence: string;
  readonly sourceDigest: string;
  readonly inkToken: string;
}

async function manifest(): Promise<readonly ManifestRecord[]> {
  const parsed: unknown = JSON.parse(await readFile(path.join(plateDir, "manifest.json"), "utf8"));
  return (parsed as { plates: readonly ManifestRecord[] }).plates;
}

const stylesheet = () => kitStylesheet("plate/plate.css", domainDir);

describe("a plate", () => {
  it("is an image in the flow, and it is decoration, so its alt text is empty", () => {
    render(<Plate name="astrolabe" />);
    const plate = screen.getByRole("presentation", { hidden: true });

    expect(plate.tagName).toBe("IMG");
    expect(plate).toHaveAttribute("alt", "");
  });

  it("resolves the file the generator wrote", () => {
    render(<Plate name="armillary" />);

    expect(screen.getByRole("presentation", { hidden: true })).toHaveAttribute(
      "src",
      PLATES.armillary,
    );
  });

  it("crops to a band where a header band asks for one", () => {
    const { container } = render(<Plate name="astrolabe" fit="band" />);

    expect(container.querySelector("img")).toHaveClass("plate--band");
  });
});

describe("never behind data", () => {
  /* Read as PROPERTIES rather than as text: `object-position` is how a band crops, and a pattern over the file
   * would read it as `position` and refuse the crop. */
  it("is enforced by the stylesheet, which positions nothing and fills nothing", async () => {
    const properties = new Set<string>();
    parse(await stylesheet()).walkDecls((declaration) => {
      properties.add(declaration.prop);
    });

    expect(properties.size).toBeGreaterThan(3);
    for (const banned of ["position", "z-index", "background", "background-image"]) {
      expect(properties).not.toContain(banned);
    }
  });
});

describe("the manifest", () => {
  it("has an entry for every plate the application can render", async () => {
    const recorded = new Set((await manifest()).map((record) => record.id));
    const names = Object.keys(PLATES) as PlateName[];

    expect(names.length).toBeGreaterThan(0);
    for (const name of names) expect(recorded).toContain(name);
  });

  it("has a committed file for every entry, so an entry cannot outlive its plate", async () => {
    const records = await manifest();
    const files = await Promise.all(
      records.map((record) => readFile(path.join(plateDir, `${record.id}.png`))),
    );

    expect(files).toHaveLength(records.length);
    for (const bytes of files) expect(bytes.length).toBeGreaterThan(0);
  });

  it("names a source, a licence and a digest for each, which is what makes it auditable", async () => {
    for (const record of await manifest()) {
      expect(record.source).toMatch(/^https?:\/\//);
      expect(record.licence.length).toBeGreaterThan(0);
      expect(record.sourceDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    }
  });

  it("records which token each plate's ink was baked from, because a plate cannot read a var()", async () => {
    for (const record of await manifest()) expect(record.inkToken).toBe("--ink-deep");
  });

  it("carries only public-domain sources, which is what generated illustration means here", async () => {
    for (const record of await manifest()) {
      expect(record.licence.toLowerCase()).toMatch(/public domain|cc0/);
    }
  });

  it("depicts horological and astronomical instruments, and nothing else", async () => {
    const instruments =
      /orrery|sundial|escapement|astrolabe|armillary|star chart|clock|planisphere|quadrant|sphere/i;

    for (const record of await manifest()) expect(record.subject).toMatch(instruments);
  });
});
