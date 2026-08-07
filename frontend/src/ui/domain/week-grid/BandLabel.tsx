/* THE GUTTER LABEL ON A BAND, which is a reading or a control depending on whether anything is behind it.
 *
 * AN EMPTY SLOT'S LABEL IS THE ONE INVITATION ON THIS SCREEN. Activating it opens capture prefilled with the slot's
 * Area and an estimate equal to the slot's duration, which is what stops an unfillable slot being a dead end. A
 * window's label and an off-plan span's have nothing behind them, so they stay text: a control that did nothing would
 * be worse than a reading, because a reader would press it.
 *
 * THE TWO FORMS SHARE ONE CLASS, so the knockout over the hatch is one declaration. A button's own reset comes from
 * the bundle's preflight, which is why the class carries no font of its own here. */

export interface BandLabelProps {
  readonly label: string;
  readonly onActivate?: (() => void) | undefined;
}

export function BandLabel({ label, onActivate }: BandLabelProps) {
  if (onActivate === undefined) return <span className="week-band__label">{label}</span>;

  return (
    <button className="week-band__label" onClick={onActivate} type="button">
      {label}
    </button>
  );
}
