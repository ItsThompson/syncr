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
 * The notice as it arrives over the wire, where `stillWorks` is a plain array.
 *
 * `13-http-api.md` types the field `string[]`, and the api enforces the non-empty rule with a Pydantic schema. A
 * `string[]` is not assignable to a non-empty tuple, which is the point: the boundary is where the two models meet.
 */
export interface WireNotice extends NoticeFields {
  readonly stillWorks: readonly string[];
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
  if (first !== undefined) return { ...wire, stillWorks: [first, ...rest] };
  return null;
}

/**
 * The same narrowing for a notice that declares a total outage, which is the one shape that may name nothing.
 *
 * Separate from `noticeFrom` because the two answer different questions: this one is a caller ASSERTING that the
 * whole product is down, and that assertion belongs at a call site a reader can find rather than inside a guard
 * that would otherwise have to infer it from an empty array.
 */
export function outageFrom(wire: WireNotice): Notice {
  return { ...wire, stillWorks: [], isWholeProductDown: true };
}
