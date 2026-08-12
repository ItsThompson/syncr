/* Fixture: `await import` with a BACKTICK-quoted specifier.
 *
 * This is the shape that got through. The specifier pattern accepted single and double quotes only,
 * so a real fetching component passed every check, and `vite build` went from 118 to 119 modules with
 * the code in the chunk: it worked in dev, in test and in production. */

export async function fetchOnTheSly(): Promise<unknown> {
  const { apiFetch } = await import(`../../api/client`);
  return apiFetch("/v1/areas");
}
