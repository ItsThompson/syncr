/* Fixture: the three families review iteration 4 proved reach `dist` with every check green.
 *
 * Tailwind's PAREN form of an arbitrary value, which its own documentation recommends for a CSS
 * variable and which both arbitrary-value patterns were blind to because both were written around
 * `[`. And `delay-*` and `will-change-*`, whose properties this repo's stylelint list already bans
 * while the markup scan had no root for either.
 *
 * Every one of these is judged by what it COMPILES TO, so a spelling Tailwind adds next cannot walk
 * past it. The two that emit an ordinary property, `w-(--wide)` and `bg-(--tint)`, are caught by the
 * arbitrary-value rule instead: no emitted declaration distinguishes them from `w-sidebar`. */

export function ParenForms() {
  return (
    <div className="blur-(--haze) backdrop-blur-(--haze) shadow-(--halo)">
      <span className="w-(--wide) bg-(--tint)" />
      <span className="delay-300 will-change-transform" />
    </div>
  );
}
