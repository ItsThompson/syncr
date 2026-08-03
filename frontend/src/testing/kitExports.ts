/* The components a barrel exports, read from the barrel rather than from a list beside it.
 *
 * A test that names the components itself cannot report the one it does not name: a component added to the
 * barrel and not to the list passes, which is how `CommandItem` came to be exported and mounted nowhere.
 * The set is derived here so a test asserts its own coverage against what the module actually exports.
 *
 * A COMPONENT IS AN EXPORTED FUNCTION WITH A CAPITALISED NAME, which is React's own rule rather than a
 * convention this file invents: JSX resolves a lowercase name to a DOM tag and a capitalised one to the
 * value in scope. It is what separates `Button` from the layer's other exported functions, `dayLabel` and
 * `snapClock`, which are date and clock arithmetic. */

const CAPITALISED = /^[A-Z]/;

export function componentNamesIn(barrel: Readonly<Record<string, unknown>>): string[] {
  return Object.entries(barrel)
    .filter(([name, value]) => typeof value === "function" && CAPITALISED.test(name))
    .map(([name]) => name)
    .toSorted();
}
