/* THE GUTTER LABEL ON A BAND, which is a reading or a control depending on whether the caller hands it an
 * activation.
 *
 * AN EMPTY SLOT'S LABEL IS THE ONE INVITATION ON THIS SCREEN. Activating it opens capture prefilled with the slot's
 * Area, an estimate equal to the slot's own duration, and the window it runs in, which is what stops an unfillable
 * slot being a dead end.
 *
 * WHICH BANDS GET AN ACTIVATION IS THE SCREEN'S, NOT THIS FILE'S. The week screen hands one to every band, so a
 * window's label and an off-plan span's are controls too, and activating one of those resolves to no slot and does
 * nothing.
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
