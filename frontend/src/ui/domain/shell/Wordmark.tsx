/* The wordmark, and the one lowercase serif in the system.
 *
 * Everywhere else only uppercase text is tracked out, and the wordmark of the language syncr
 * inherits is uppercase tracked serif. The product's name is lowercase by design and setting
 * it as SYNCR misreads it. Nothing else may claim the exception. */

export function Wordmark() {
  return (
    <span className="font-serif text-stat leading-tight tracking-wordmark lowercase text-ink-deep">
      syncr
    </span>
  );
}