/* THE PLATE GENERATOR, TESTED AGAINST ITS OWN OUTPUT RATHER THAN AGAINST A SCREENSHOT.
 *
 * Three things can go wrong quietly here and each has a case: a decoder that reads a transparent source as black,
 * an encoder that writes a PNG a browser refuses, and a manifest update that reorders the file instead of adding a
 * line. The first one actually happened: the armillary plate came out as a solid field of ink with the sphere cut
 * out of it, because the source is white line art on nothing and its alpha was dropped.
 *
 * The round trip is the strongest available oracle: encode a bitmap this file made, decode it again, and compare. A
 * plate that survives that is a plate a browser can read, because the decoder implements the format rather than
 * the encoder's own habits. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { deflateSync } from "node:zlib";
import { describe, expect, it } from "vitest";

import { frontendRoot } from "../../lib/paths.ts";
import { dither, scaleToWidth } from "../dither.ts";
import { decodeToGray, encodeBitmap, type Bitmap, type GrayImage } from "../png.ts";
import { withRecord, type PlateManifest, type PlateRecord } from "../manifest.ts";

const PALETTE = { ink: "#16307f", paper: "#f4f1e8" };

function plateRecord(id: string): PlateRecord {
  return {
    id,
    subject: "Orrery",
    source: "https://example.invalid/orrery.png",
    licence: "Public domain",
    author: "unattributed",
    sourceDigest: "sha256:0",
    inkToken: "--ink-deep",
    width: 420,
    height: 420,
  };
}

function gradient(width: number, height: number): GrayImage {
  const gray = new Uint8Array(width * height);
  for (let index = 0; index < gray.length; index += 1) {
    gray[index] = Math.round((255 * (index % width)) / (width - 1));
  }
  return { width, height, gray };
}

function bitmapOf(width: number, height: number, ink: (x: number, y: number) => boolean): Bitmap {
  const bits = new Uint8Array(width * height);
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      bits[row * width + column] = ink(column, row) ? 1 : 0;
    }
  }
  return { width, height, ink: bits };
}

/** A source PNG in the colour type given, built by the encoder's own chunk writer through a raw deflate. */
function truecolourPng(pixels: readonly [number, number, number, number][], width: number): Buffer {
  const height = pixels.length / width;
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let row = 0; row < height; row += 1) {
    const start = row * (width * 4 + 1);
    raw[start] = 0;
    for (let column = 0; column < width; column += 1) {
      const [red, green, blue, alpha] = pixels[row * width + column];
      raw.set([red, green, blue, alpha], start + 1 + column * 4);
    }
  }

  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;

  const chunks: Buffer[] = [Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])];
  for (const [type, data] of [
    ["IHDR", header],
    ["IDAT", deflateSync(raw)],
    ["IEND", Buffer.alloc(0)],
  ] as const) {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length, 0);
    const typed = Buffer.concat([Buffer.from(type, "latin1"), data]);
    const crc = Buffer.alloc(4);
    // The decoder does not verify the checksum, so a zero here is honest rather than a fake.
    chunks.push(length, typed, crc);
  }
  return Buffer.concat(chunks);
}

describe("the encoder", () => {
  it("writes a PNG the decoder reads back pixel for pixel", () => {
    const original = bitmapOf(16, 9, (x, y) => (x + y) % 2 === 0);

    const decoded = decodeToGray(encodeBitmap(original, PALETTE));

    expect(decoded.width).toBe(16);
    expect(decoded.height).toBe(9);
    for (let index = 0; index < original.ink.length; index += 1) {
      const isInk = decoded.gray[index] < 128;
      expect(isInk).toBe(original.ink[index] === 1);
    }
  });

  it("writes one bit per pixel with a two-entry palette, which is what keeps a plate small", () => {
    const bytes = encodeBitmap(
      bitmapOf(64, 64, () => true),
      PALETTE,
    );
    const header = bytes.subarray(bytes.indexOf("IHDR") + 4);

    expect(header[8]).toBe(1);
    expect(header[9]).toBe(3);
    expect(bytes.includes("PLTE")).toBe(true);
    expect(bytes.length).toBeLessThan(64 * 64);
  });

  it("marks the paper transparent, so one plate sits on both paper surfaces", () => {
    const bytes = encodeBitmap(
      bitmapOf(8, 8, () => false),
      PALETTE,
    );
    const at = bytes.indexOf("tRNS");

    expect(at).toBeGreaterThan(0);
    expect([...bytes.subarray(at + 4, at + 6)]).toEqual([0xff, 0x00]);
  });

  it("bakes the ink it is given, so a plate's pigment comes from the token layer", () => {
    const bytes = encodeBitmap(
      bitmapOf(4, 4, () => true),
      PALETTE,
    );
    const at = bytes.indexOf("PLTE");

    expect([...bytes.subarray(at + 4, at + 7)]).toEqual([0x16, 0x30, 0x7f]);
  });
});

describe("the decoder", () => {
  /* THE DEFECT THIS CASE IS ABOUT SHIPPED ONCE. Line art published as an SVG arrives as white strokes on nothing,
   * and reading its RGB alone made the nothing black: the plate came out as a field of ink with the drawing cut
   * out of it. A transparent pixel is paper. */
  it("reads a transparent pixel as paper rather than as black", () => {
    const transparentWhite: [number, number, number, number] = [255, 255, 255, 0];
    const opaqueBlack: [number, number, number, number] = [0, 0, 0, 255];

    const decoded = decodeToGray(truecolourPng([transparentWhite, opaqueBlack], 2));

    expect(decoded.gray[0]).toBe(255);
    expect(decoded.gray[1]).toBe(0);
  });

  it("refuses a source it cannot read, by name rather than by producing noise", () => {
    expect(() => decodeToGray(Buffer.from("not a png at all"))).toThrow(/signature/);
  });
});

describe("the dither", () => {
  it("turns a mid grey into ink at about half coverage", () => {
    const midGrey: GrayImage = { width: 40, height: 40, gray: new Uint8Array(1600).fill(128) };

    const coverage = dither(midGrey).ink.reduce((total, bit) => total + bit, 0) / 1600;

    expect(coverage).toBeGreaterThan(0.4);
    expect(coverage).toBeLessThan(0.6);
  });

  it("leaves white as paper and black as ink, so the extremes are not dithered away", () => {
    const white: GrayImage = { width: 8, height: 8, gray: new Uint8Array(64).fill(255) };
    const black: GrayImage = { width: 8, height: 8, gray: new Uint8Array(64).fill(0) };

    expect([...dither(white).ink]).toEqual(Array.from({ length: 64 }, () => 0));
    expect([...dither(black).ink]).toEqual(Array.from({ length: 64 }, () => 1));
  });

  it("carries tone across a gradient rather than clipping it at the midpoint", () => {
    const bitmap = dither(gradient(64, 8));
    const left = bitmap.ink.slice(0, 16).reduce((total, bit) => total + bit, 0);
    const right = bitmap.ink.slice(48, 64).reduce((total, bit) => total + bit, 0);

    expect(left).toBeGreaterThan(right);
  });

  it("steepens around the midpoint when asked, which is what lifts a haze off the paper", () => {
    const nearlyWhite: GrayImage = { width: 32, height: 32, gray: new Uint8Array(1024).fill(180) };

    const plain = dither(nearlyWhite).ink.reduce((total, bit) => total + bit, 0);
    const steep = dither(nearlyWhite, 2).ink.reduce((total, bit) => total + bit, 0);

    expect(steep).toBeLessThan(plain);
  });
});

describe("the scale", () => {
  it("averages a box of source pixels rather than sampling one, which is what makes tone", () => {
    const checker = bitmapOf(4, 4, (x, y) => (x + y) % 2 === 0);
    const source: GrayImage = {
      width: 4,
      height: 4,
      gray: new Uint8Array([...checker.ink].map((bit) => (bit === 1 ? 0 : 255))),
    };

    const scaled = scaleToWidth(source, 2);

    expect(scaled.width).toBe(2);
    expect([...scaled.gray]).toEqual([128, 128, 128, 128]);
  });

  it("keeps the source's proportion, so a band crops rather than stretching", () => {
    const scaled = scaleToWidth(gradient(100, 50), 40);

    expect(scaled.width).toBe(40);
    expect(scaled.height).toBe(20);
  });

  it("leaves a source no wider than the target alone", () => {
    const source = gradient(20, 10);

    expect(scaleToWidth(source, 40)).toBe(source);
  });
});

describe("the manifest", () => {
  it("adds a plate in id order, so a second plate is a one-entry diff", () => {
    const manifest: PlateManifest = { plates: [plateRecord("sundial")] };

    const updated = withRecord(manifest, plateRecord("armillary"));

    expect(updated.plates.map((plate) => plate.id)).toEqual(["armillary", "sundial"]);
  });

  it("replaces an entry rather than duplicating it, so regenerating a plate is idempotent", () => {
    const manifest: PlateManifest = { plates: [plateRecord("orrery")] };

    const updated = withRecord(manifest, { ...plateRecord("orrery"), width: 600 });

    expect(updated.plates).toHaveLength(1);
    expect(updated.plates[0].width).toBe(600);
  });
});

describe("the committed plates", () => {
  /* The generator's output is committed, so the artifact itself is checkable: each plate is a PNG this decoder
   * reads, at the size the manifest records. A plate that stopped being readable would otherwise be discovered by
   * a reader looking at a broken image. */
  it("are readable PNGs at the size the manifest records", async () => {
    const plateDir = path.join(frontendRoot, "src", "assets", "plates");
    const manifest: { plates: readonly PlateRecord[] } = JSON.parse(
      await readFile(path.join(plateDir, "manifest.json"), "utf8"),
    );

    expect(manifest.plates.length).toBeGreaterThan(0);
    for (const plate of manifest.plates) {
      const decoded = decodeToGray(await readFile(path.join(plateDir, `${plate.id}.png`)));
      expect(decoded.width).toBe(plate.width);
      expect(decoded.height).toBe(plate.height);
    }
  });
});
