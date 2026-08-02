/* The design rules that live in CSS.
 *
 * No shareable config is extended, deliberately. A shareable config carries formatting taste, and
 * every rule below has to earn its place by naming a design decision it protects. A reader can
 * therefore tell what the linter is FOR by reading it.
 *
 * The markup half of the same rules lives in `scripts/lint-markup`, which sees the class names and
 * data attributes no CSS linter can, and the artifact half lives in `scripts/check-bundle`, which
 * reads the stylesheet a browser downloads. The three ask the same question of three inputs, so the
 * banned property list is IMPORTED from the module they share rather than restated here: three copies
 * is how a shape came to be refused in CSS and permitted in a TSX style object.
 *
 * ESCAPE HATCH. A `stylelint-disable` comment must carry a reason, and an unused one fails, so an
 * exception is auditable and cannot outlive the case it was written for. */

import { BANNED_PROPERTIES, FILTER_PROPERTIES } from "./scripts/lib/declarations.ts";

const LAYER_ZERO_REFERENCE = String.raw`/var\(\s*--(cobalt|cream|oxide|verdigris|amber)-\d/`;
const LAYER_ZERO_PIGMENT = String.raw`/var\(\s*--pigment-area-/`;

/* Print has no blur, in every spelling a browser accepts. An empty allowed list means no value is. */
const NO_VALUE_ALLOWED = Object.fromEntries(
  [...FILTER_PROPERTIES].map((property) => [property, []]),
);

export default {
  reportDescriptionlessDisables: true,
  reportNeedlessDisables: true,
  reportInvalidScopeDisables: true,

  rules: {
    // The system is drawn in one ink, and every value it is drawn with is a token. A raw color
    // outside layer 0 is a pigment nobody sealed.
    "color-no-hex": true,
    "color-named": "never",
    "function-disallowed-list": [
      "rgb",
      "rgba",
      "hsl",
      "hsla",
      "hwb",
      "lab",
      "lch",
      "oklab",
      "oklch",
    ],

    // A component reads a layer 1 semantic name. Layer 0 is raw pigment ramps, and every step
    // there ends in a number, which is what separates --amber-500 from the layer 1 --amber-wash.
    "declaration-property-value-disallowed-list": {
      "/.*/": [LAYER_ZERO_REFERENCE, LAYER_ZERO_PIGMENT],
      // The one hard offset lives in --shadow-hard, on overlays that must lift off the page.
      "box-shadow": [String.raw`/^(?!(none|var\(--shadow-hard\))$)/`],
      // No `outline: none` without an equivalent replacement. The system draws its own ring, so
      // removing one leaves a keyboard-first tool with no focus indicator at all.
      outline: ["/^none$/", "/^0$/"],
      // Radius is zero. `50%` survives for the four legal circles.
      "border-radius": [String.raw`/^(?!(0|50%|var\(--radius\))$)/`],
    },

    // MOTION IS ZERO, WITHOUT EXCEPTION. Nothing eases, fades, slides, shimmers or spins.
    "property-disallowed-list": [...BANNED_PROPERTIES],
    "at-rule-disallowed-list": ["keyframes"],

    // Print has no blur.
    "declaration-property-value-allowed-list": NO_VALUE_ALLOWED,
  },

  overrides: [
    {
      // LAYER 0 is where a raw pigment is allowed to exist, and the only place.
      files: ["src/tokens/primitives.css"],
      rules: {
        "color-no-hex": null,
      },
    },
    {
      // The token layer defines the values every other file reads, so it references layer 0 by
      // name and declares the gradients that are the system's one texture primitive.
      files: ["src/tokens/*.css"],
      rules: {
        "declaration-property-value-disallowed-list": {
          outline: ["/^none$/", "/^0$/"],
        },
      },
    },
  ],
};
