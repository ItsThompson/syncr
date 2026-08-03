/* The components a barrel exports, read from the barrel rather than from a list beside it.
 *
 * A test that names the components itself cannot report the one it does not name: a component added to the
 * barrel and not to the list passes, and a barrel export that nothing mounts or hands a ref stays invisible.
 * The set is derived here so a test asserts its own coverage against what the module actually exports. *
 * A COMPONENT IS AN EXPORT WITH A CAPITALISED NAME THAT JSX CAN RENDER, which is React's own rule rather than
 * a convention this file invents: JSX resolves a lowercase name to a DOM tag and a capitalised one to the
 * value in scope. The capital is what separates `Button` from the layer's other exported functions,
 * `dayLabel` and `snapClock`, which are date and clock arithmetic.
 *
 * A function is one such value and so is a `memo` or `forwardRef` object, which is why the type is not the
 * test: those wrappers return an object, and reading only functions would silently drop a wrapped component
 * out of every check that derives its coverage from here. */

const CAPITALISED = /^[A-Z]/;
const REACT_VALUE = "react.";

/** True for a value JSX will render: a component function, or one of React's own wrapper objects. */
function isRenderable(value: unknown): boolean {
  if (typeof value === "function") return true;
  if (typeof value !== "object" || value === null) return false;
  if (!("$$typeof" in value)) return false;
  const tag = value.$$typeof;
  return typeof tag === "symbol" && tag.description?.startsWith(REACT_VALUE) === true;
}

export function componentNamesIn(barrel: Readonly<Record<string, unknown>>): string[] {
  return Object.entries(barrel)
    .filter(([name, value]) => CAPITALISED.test(name) && isRenderable(value))
    .map(([name]) => name)
    .toSorted();
}
