/* THE NOTICE, AND THE FIELD THAT IS A TYPE RULE RATHER THAN A CONVENTION.
 *
 * `stillWorks` may not be empty. Every degradation notice in this product has to name the capability that
 * survives, because a notice that says only what broke leaves a reader unable to decide what to do next: the
 * plan is still readable when the calendar write fails, and the week is still solvable when one ICS feed is
 * unreachable. A non-empty tuple is what makes that the compiler's business instead of a reviewer's.
 *
 * THE ONE CASE WITH NOTHING TO SAY IS THE WHOLE PRODUCT BEING DOWN, and it is a second arm of the union rather
 * than an empty array the first arm tolerates. A notice claiming a total outage says so in a field, which is a
 * thing a reader of the code can search for, and it is the only shape that may carry an empty list.
 *
 * VOLUME IS POSITION AND PIGMENT IS KIND. They are two fields because they answer two questions: how loudly a
 * reader should care, and what sort of thing happened. There is no `blocking` volume: level 4 is deliberately
 * unused, and `NoticeCard`, `NoticePanel` and `NoticeStrip` are the whole set.
 *
 * THE WIRE'S OWN SHAPE IS NARROWED HERE, at the boundary, by `noticeFrom`. The api types the field as a plain
 * array, so without a guard in this file the first screen to render a response would meet a type error with `as
 * Notice` sitting next to it, and the cast would reopen the hole the tuple closes. */

export type NoticeVolume = "inline" | "panel" | "banner";

/**
 * What kind of thing happened.
 *
 * `info` spends no signal pigment at all, `amber` needs attention with nothing broken, `oxide` is a failure,
 * and `verdigris` is a confirmation used sparingly.
 */
export type NoticePigment = "info" | "amber" | "oxide" | "verdigris";

/** At most one action per notice, so a reader is never asked to choose between two repairs. */
export interface NoticeAction {
  readonly label: string;
  readonly href: string;
}

/** What the notice is about, where it is about one thing. */
export interface NoticeScope {
  readonly screen?: string | undefined;
  readonly blockId?: string | undefined;
  readonly sourceId?: string | undefined;
  readonly date?: string | undefined;
  /** Every day this condition puts in doubt, earliest first. A surface marks a day from this rather than computing anything. */
  readonly dates?: readonly string[] | undefined;
}

interface NoticeFields {
  readonly id: string;
  readonly volume: NoticeVolume;
  readonly pigment: NoticePigment;
  readonly title: string;
  readonly detail: string;
  /** Capabilities that are currently unavailable. */
  readonly unavailable: readonly string[];
  /** ISO instant: how long the condition has held, or null while it is not known. */
  readonly since: string | null;
  readonly action: NoticeAction | null;
  readonly scope: NoticeScope | null;
}

/** A list the type refuses to let a caller empty. */
type NonEmptyStrings = readonly [string, ...string[]];

export type Notice = NoticeFields &
  (
    | {
        /** What still works. At least one, always. */
        readonly stillWorks: NonEmptyStrings;
        readonly isWholeProductDown?: false | undefined;
      }
    | {
        readonly stillWorks: readonly [];
        readonly isWholeProductDown: true;
      }
  );

/**
 * The notice as it arrives over the wire.
 *
 * FOUR FIELDS THE KIT REQUIRES ARE OPTIONAL HERE, and that is the document rather than a convenience. The api's
 * schema requires `id`, `volume`, `pigment`, `title`, `detail` and `stillWorks`, and leaves the rest to be omitted:
 * a notice about no one thing carries no scope, one with no repair carries no action, and one whose age is unknown
 * carries no instant. The kit's own type has no absent case for any of them, because a component rendering a
 * notice should not have to tell an omitted list from an empty one. Narrowing is where the two models meet.
 *
 * `stillWorks` is a plain array here for the same reason: `13-http-api.md` types it `string[]` and the api enforces
 * the non-empty rule with a Pydantic schema, so the array is what arrives and the non-empty tuple is what the kit
 * renders from.
 */
export interface WireNotice {
  readonly id: string;
  readonly volume: NoticeVolume;
  readonly pigment: NoticePigment;
  readonly title: string;
  readonly detail: string;
  readonly stillWorks: readonly string[];
  readonly unavailable?: readonly string[] | undefined;
  readonly since?: string | null | undefined;
  readonly action?: NoticeAction | null | undefined;
  readonly scope?: WireNoticeScope | null | undefined;
}

/** The scope as the document types it: every member optional, and nullable with it. */
interface WireNoticeScope {
  readonly screen?: string | null | undefined;
  readonly blockId?: string | null | undefined;
  readonly sourceId?: string | null | undefined;
  readonly date?: string | null | undefined;
  readonly dates?: readonly string[] | null | undefined;
}

/** A wire scope with its nulls read as absences, which is what the kit's own scope means by them. */
function scopeFrom(scope: WireNoticeScope | null | undefined): NoticeScope | null {
  if (scope === null || scope === undefined) return null;
  return {
    screen: scope.screen ?? undefined,
    blockId: scope.blockId ?? undefined,
    sourceId: scope.sourceId ?? undefined,
    date: scope.date ?? undefined,
    dates: scope.dates ?? undefined,
  };
}

/**
 * A wire notice narrowed to the kit's own type, or null when it names no surviving capability.
 *
 * THIS FUNCTION IS THE WHOLE REASON THE TYPE RULE SURVIVES CONTACT WITH A RESPONSE. Without it the first screen to
 * render a notice from the api hits `TS2322`, and the cheapest way out is `as Notice`, which is exactly the escape
 * the non-empty tuple exists to close: a cast would let a notice that says only what broke reach a reader.
 *
 * Returning null rather than throwing is deliberate. A malformed notice is a degradation of the notice system
 * itself, and a thrown error inside a render would take the screen down over a banner. The caller drops it and,
 * where it matters, counts it.
 */
export function noticeFrom(wire: WireNotice): Notice | null {
  const [first, ...rest] = wire.stillWorks;
  if (first === undefined) return null;
  return {
    id: wire.id,
    volume: wire.volume,
    pigment: wire.pigment,
    title: wire.title,
    detail: wire.detail,
    unavailable: wire.unavailable ?? [],
    stillWorks: [first, ...rest],
    since: wire.since ?? null,
    action: wire.action ?? null,
    scope: scopeFrom(wire.scope),
  };
}

/**
 * The same narrowing for a notice that declares a total outage, which is the one shape that may name nothing.
 *
 * Separate from `noticeFrom` because the two answer different questions: this one is a caller ASSERTING that the
 * whole product is down, and that assertion belongs at a call site a reader can find rather than inside a guard
 * that would otherwise have to infer it from an empty array.
 */
export function outageFrom(wire: WireNotice): Notice {
  return {
    id: wire.id,
    volume: wire.volume,
    pigment: wire.pigment,
    title: wire.title,
    detail: wire.detail,
    unavailable: wire.unavailable ?? [],
    since: wire.since ?? null,
    action: wire.action ?? null,
    scope: scopeFrom(wire.scope),
    stillWorks: [],
    isWholeProductDown: true,
  };
}

/**
 * The wire's notices that render at one volume, narrowed, with any that name no surviving capability dropped.
 *
 * ONE CONDITION ARRIVES AS TWO NOTICES. The api raises the write target's expiry at banner volume and at panel
 * volume, as two values with a shared identity root, because a notice carries one volume: volume is where it
 * renders. So the two surfaces that show it each ask for their own volume, and neither has to know that the
 * other exists. Filtering here rather than at each call site is what stops the top bar rendering a panel notice
 * as a banner the first time a condition gains a second volume.
 */
export function noticesAt(volume: NoticeVolume, wire: readonly WireNotice[]): readonly Notice[] {
  return wire.flatMap((one) => {
    if (one.volume !== volume) return [];
    const narrowed = noticeFrom(one);
    return narrowed === null ? [] : [narrowed];
  });
}
