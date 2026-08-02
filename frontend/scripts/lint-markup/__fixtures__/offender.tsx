/* Fixture: every markup rule, violated once. Not reachable from the app. */

export function Offender() {
  return (
    <div className="w-[13px] rounded-md transition-colors" data-busy="">
      <span className={"text-[11px] animate-spin"} />
      <span style={{ color: "var(--cobalt-600)" }} />
    </div>
  );
}
