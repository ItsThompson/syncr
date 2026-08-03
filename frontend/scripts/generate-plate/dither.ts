/* THE HOUSE STYLE: A DITHERED PLATE, WHICH IS WHAT A TWO-COLOUR SYSTEM HAS INSTEAD OF A PHOTOGRAPH.
 *
 * The product is drawn in one ink on paper and has no grey. A photograph reduced by a threshold loses everything
 * between the two, so the tone is carried by the DENSITY of ink instead: Floyd and Steinberg's error diffusion
 * pushes the rounding error of each pixel onto its neighbours, so a mid-grey becomes a field of ink at half
 * coverage. That is the same trick a newspaper's halftone plays, which is why it reads as an engraving rather than
 * as a bad photograph.
 *
 * THE SOURCE IS SCALED FIRST, AND BY AVERAGE RATHER THAN BY SAMPLE. A plate is decoration at a few hundred pixels
 * and the sources are a thousand or more, and dithering first would throw away the very detail the scale is meant
 * to keep: nearest-neighbour sampling of a dithered field produces moire. Averaging a box of source pixels is what
 * turns detail into tone, which is the input error diffusion wants. */

import type { Bitmap, GrayImage } from "./png.ts";

/** The diffusion weights, over sixteen: right, and the three below. */
const RIGHT = 7 / 16;
const BELOW_LEFT = 3 / 16;
const BELOW = 5 / 16;
const BELOW_RIGHT = 1 / 16;

const MIDPOINT = 128;

/** Averages each box of source pixels into one, which is what turns detail into tone. */
export function scaleToWidth(image: GrayImage, width: number): GrayImage {
  if (width >= image.width) return image;
  const height = Math.max(1, Math.round((image.height * width) / image.width));
  const gray = new Uint8Array(width * height);

  for (let row = 0; row < height; row += 1) {
    const fromRow = Math.floor((row * image.height) / height);
    const toRow = Math.max(fromRow + 1, Math.floor(((row + 1) * image.height) / height));
    for (let column = 0; column < width; column += 1) {
      const fromColumn = Math.floor((column * image.width) / width);
      const toColumn = Math.max(fromColumn + 1, Math.floor(((column + 1) * image.width) / width));
      let total = 0;
      let counted = 0;
      for (let y = fromRow; y < toRow; y += 1) {
        for (let x = fromColumn; x < toColumn; x += 1) {
          total += image.gray[y * image.width + x];
          counted += 1;
        }
      }
      gray[row * width + column] = Math.round(total / counted);
    }
  }
  return { width, height, gray };
}

/**
 * Error-diffusion dither to one bit, where 1 is ink.
 *
 * `contrast` steepens the source around its midpoint before the diffusion runs. A scan of an engraving is rarely
 * black on white: it is charcoal on ivory, and diffusing that directly puts a haze of ink over the whole plate,
 * including the paper it was drawn on.
 */
export function dither(image: GrayImage, contrast = 1): Bitmap {
  const { width, height } = image;
  const error = new Float32Array(width * height);
  const ink = new Uint8Array(width * height);

  for (let index = 0; index < ink.length; index += 1) {
    const steepened = MIDPOINT + (image.gray[index] - MIDPOINT) * contrast;
    error[index] += Math.min(255, Math.max(0, steepened));
  }

  for (let row = 0; row < height; row += 1) {
    for (let column = 0; column < width; column += 1) {
      const index = row * width + column;
      const wanted = error[index];
      const drawn = wanted < MIDPOINT ? 0 : 255;
      ink[index] = drawn === 0 ? 1 : 0;
      const remainder = wanted - drawn;

      const isLastColumn = column + 1 >= width;
      const isLastRow = row + 1 >= height;
      if (!isLastColumn) error[index + 1] += remainder * RIGHT;
      if (isLastRow) continue;
      if (column > 0) error[index + width - 1] += remainder * BELOW_LEFT;
      error[index + width] += remainder * BELOW;
      if (!isLastColumn) error[index + width + 1] += remainder * BELOW_RIGHT;
    }
  }

  return { width, height, ink };
}
