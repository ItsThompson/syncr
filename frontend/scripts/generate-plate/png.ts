/* PNG IN, PNG OUT, WITH NO IMAGE LIBRARY.
 *
 * The generator reads a public-domain source and writes a two-colour plate, and both halves are small enough to
 * write against the format rather than pull a dependency that ships a decoder for every format there is. What is
 * supported is stated rather than guessed at: 8-bit non-interlaced PNG in any of the five colour types, which is
 * what every source on Wikimedia Commons that this product would use actually is. Anything else is refused by name
 * so a reader converts the file rather than debugging a plate that came out as noise.
 *
 * THE PLATE IS WRITTEN AS A 1-BIT INDEXED PNG WITH A TWO-ENTRY PALETTE AND A TRANSPARENT PAPER. Ink is the only
 * opaque colour, so the plate sits on whichever paper surface it lands on and needs no second file for the raised
 * one. It is also what keeps the committed artifact small: a dithered bitmap is high-entropy and one bit per pixel
 * is sixteen times less of it than RGBA. */

import { deflateSync, inflateSync, crc32 } from "node:zlib";

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Bytes per pixel by PNG colour type, at bit depth 8. */
const CHANNELS: Readonly<Record<number, number>> = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };

export interface GrayImage {
  readonly width: number;
  readonly height: number;
  /** One byte of luminance per pixel, row-major. */
  readonly gray: Uint8Array;
}

export interface Bitmap {
  readonly width: number;
  readonly height: number;
  /** One byte per pixel, 1 for ink and 0 for paper. */
  readonly ink: Uint8Array;
}

interface Chunk {
  readonly type: string;
  readonly data: Buffer;
}

function readChunks(bytes: Buffer): Chunk[] {
  if (!bytes.subarray(0, 8).equals(SIGNATURE)) throw new Error("not a PNG: the signature is wrong");
  const chunks: Chunk[] = [];
  let offset = 8;
  while (offset + 8 <= bytes.length) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.subarray(offset + 4, offset + 8).toString("latin1");
    chunks.push({ type, data: bytes.subarray(offset + 8, offset + 8 + length) });
    offset += 12 + length;
    if (type === "IEND") break;
  }
  return chunks;
}

/** Undoes the per-scanline filter each row carries, in place, which is what makes the bytes pixels. */
/** Undoes the per-scanline filter each row carries, which is what makes the bytes samples. */
function unfilter(raw: Buffer, stride: number, height: number, bytesPerPixel: number): Buffer {
  const out = Buffer.alloc(stride * height);
  let position = 0;
  for (let row = 0; row < height; row += 1) {
    const filter = raw[position];
    position += 1;
    const line = raw.subarray(position, position + stride);
    position += stride;
    const target = out.subarray(row * stride, (row + 1) * stride);
    const above = row === 0 ? null : out.subarray((row - 1) * stride, row * stride);
    for (let index = 0; index < stride; index += 1) {
      const left = index >= bytesPerPixel ? target[index - bytesPerPixel] : 0;
      const up = above === null ? 0 : above[index];
      const upLeft = above === null || index < bytesPerPixel ? 0 : above[index - bytesPerPixel];
      const value = line[index];
      if (filter === 0) target[index] = value;
      else if (filter === 1) target[index] = (value + left) & 0xff;
      else if (filter === 2) target[index] = (value + up) & 0xff;
      else if (filter === 3) target[index] = (value + ((left + up) >> 1)) & 0xff;
      else if (filter === 4) target[index] = (value + paeth(left, up, upLeft)) & 0xff;
      else throw new Error(`unsupported PNG row filter ${filter}`);
    }
  }
  return out;
}

function paeth(left: number, up: number, upLeft: number): number {
  const estimate = left + up - upLeft;
  const toLeft = Math.abs(estimate - left);
  const toUp = Math.abs(estimate - up);
  const toUpLeft = Math.abs(estimate - upLeft);
  if (toLeft <= toUp && toLeft <= toUpLeft) return left;
  return toUp <= toUpLeft ? up : upLeft;
}

/* Rec. 709 luminance, which is the same weighting the contrast ledger uses, so a plate darkens the way a reader's
 * eye says it should rather than the way an unweighted average does. */
function luminance(red: number, green: number, blue: number): number {
  return Math.round(0.2126 * red + 0.7152 * green + 0.0722 * blue);
}

/* A TRANSPARENT SOURCE PIXEL IS PAPER, WHICH IS WHY ALPHA IS COMPOSITED RATHER THAN DROPPED. Line art published
 * as an SVG arrives as white strokes on nothing, and reading its RGB alone makes the nothing black: the first
 * armillary-sphere plate came out as a solid field of ink with the sphere cut out of it. A plate sits on paper, so
 * the source is composited over white before its tone is read. */
function overPaper(value: number, alpha: number): number {
  return Math.round((value * alpha + 255 * (255 - alpha)) / 255);
}

const SUB_BYTE_DEPTHS = new Set([1, 2, 4]);

export function decodeToGray(bytes: Buffer): GrayImage {
  const chunks = readChunks(bytes);
  const header = chunks.find((each) => each.type === "IHDR");
  if (header === undefined) throw new Error("not a PNG: there is no IHDR");

  const width = header.data.readUInt32BE(0);
  const height = header.data.readUInt32BE(4);
  const bitDepth = header.data[8];
  const colourType = header.data[9];
  const interlace = header.data[12];
  const channels = CHANNELS[colourType];
  if (channels === undefined) throw new Error(`unsupported PNG colour type ${colourType}`);
  if (interlace !== 0) {
    throw new Error("unsupported interlaced PNG: convert the source to non-interlaced");
  }
  if (bitDepth !== 8 && !SUB_BYTE_DEPTHS.has(bitDepth)) {
    throw new Error(`unsupported bit depth ${bitDepth}: convert the source to 8-bit`);
  }
  if (bitDepth !== 8 && channels !== 1) {
    throw new Error(`unsupported PNG: ${bitDepth} bits with ${channels} channels`);
  }

  const palette = chunks.find((each) => each.type === "PLTE")?.data;
  if (colourType === 3 && palette === undefined) throw new Error("indexed PNG with no PLTE");

  const compressed = Buffer.concat(
    chunks.filter((each) => each.type === "IDAT").map((each) => each.data),
  );
  const bitsPerPixel = bitDepth * channels;
  const stride = Math.ceil((width * bitsPerPixel) / 8);
  const raw = unfilter(inflateSync(compressed), stride, height, Math.max(1, bitsPerPixel >> 3));

  /* One sample, wherever the packing puts it. A sub-byte depth holds several samples in a byte, most significant
   * first, which is the same order the encoder below writes them in. */
  const sample = (row: number, column: number, channel: number): number => {
    if (bitDepth === 8) return raw[row * stride + column * channels + channel];
    const bit = column * bitDepth;
    return (raw[row * stride + (bit >> 3)] >> (8 - bitDepth - (bit & 7))) & ((1 << bitDepth) - 1);
  };
  const maximum = (1 << bitDepth) - 1;

  const gray = new Uint8Array(width * height);
  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      const index = row * width + column;
      if (colourType === 3) {
        const entry = sample(row, column, 0) * 3;
        gray[index] = luminance(palette![entry], palette![entry + 1], palette![entry + 2]);
      } else if (colourType === 0) {
        gray[index] = Math.round((sample(row, column, 0) * 255) / maximum);
      } else if (colourType === 4) {
        gray[index] = overPaper(sample(row, column, 0), sample(row, column, 1));
      } else if (colourType === 6) {
        const alpha = sample(row, column, 3);
        gray[index] = luminance(
          overPaper(sample(row, column, 0), alpha),
          overPaper(sample(row, column, 1), alpha),
          overPaper(sample(row, column, 2), alpha),
        );
      } else {
        gray[index] = luminance(
          sample(row, column, 0),
          sample(row, column, 1),
          sample(row, column, 2),
        );
      }
    }
  }
  return { width, height, gray };
}

function encodeChunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typed = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(typed), 0);
  return Buffer.concat([length, typed, checksum]);
}

function rgb(hex: string): Buffer {
  const digits = /^#([0-9a-f]{6})$/i.exec(hex);
  if (digits === null) throw new Error(`${hex} is not a six-digit hex colour`);
  return Buffer.from(digits[1], "hex");
}

export interface PlatePalette {
  /** The ink the plate is drawn in, as a six-digit hex resolved from the token layer. */
  readonly ink: string;
  /** The paper it would sit on. Written as the second palette entry and made fully transparent. */
  readonly paper: string;
}

export function encodeBitmap(bitmap: Bitmap, palette: PlatePalette): Buffer {
  const { width, height, ink } = bitmap;
  const stride = Math.ceil(width / 8);
  const raw = Buffer.alloc((stride + 1) * height);

  for (let row = 0; row < height; row += 1) {
    const start = row * (stride + 1);
    // Filter 0: a dithered row correlates with nothing, so a predictor costs bytes rather than saving them.
    raw[start] = 0;
    for (let column = 0; column < width; column += 1) {
      // Index 0 is ink and index 1 is paper, so a set bit is paper: the plate's own ink is the drawn half.
      if (ink[row * width + column] === 0) {
        raw[start + 1 + (column >> 3)] |= 0x80 >> (column & 7);
      }
    }
  }

  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 1; // bit depth
  header[9] = 3; // colour type: indexed
  header[12] = 0; // no interlace

  return Buffer.concat([
    SIGNATURE,
    encodeChunk("IHDR", header),
    encodeChunk("PLTE", Buffer.concat([rgb(palette.ink), rgb(palette.paper)])),
    // Ink is opaque and paper is not, so the plate takes the surface it lands on rather than carrying its own.
    encodeChunk("tRNS", Buffer.from([0xff, 0x00])),
    encodeChunk("IDAT", deflateSync(raw, { level: 9 })),
    encodeChunk("IEND", Buffer.alloc(0)),
  ]);
}
