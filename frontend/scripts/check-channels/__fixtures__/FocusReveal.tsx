/* Fixture: the reveal written as a variant utility instead of a declaration, which must count the same.
   The bare `sr-only` beside it records nothing, because a utility is read only through a variant. */

export function FocusReveal() {
  return (
    <a className="sr-only focus-visible:not-sr-only" href="#main">
      Skip to content
    </a>
  );
}
