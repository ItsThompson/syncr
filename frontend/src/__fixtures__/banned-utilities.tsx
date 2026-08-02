/* A probe, not a component. Nothing imports this file and nothing should.
 *
 * It names three utilities the design language refuses, in the shape a real component would write
 * them: a `className` on a `__fixtures__` file under `src/`. Tailwind's own extractor reads every
 * string in a file it scans, so before the content scan was narrowed all three compiled into the
 * stylesheet a browser downloads, with every check green, because no check reads a `__fixtures__`
 * directory.
 *
 * `src/__fixtures__/banned-utilities.test.ts` builds the application and asserts the built stylesheet
 * carries none of them. Deleting the `@source not` rules in `theme.css` makes that test fail, which is
 * the only way to know the exclusion is still doing its job. */

export function BannedUtilities() {
  return (
    <div className="blur-(--haze) shadow-(--halo) will-change-transform delay-300 backdrop-grayscale" />
  );
}
