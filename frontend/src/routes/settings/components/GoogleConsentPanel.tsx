/* Connecting Google: the consent surface first, then a real link to it.
 *
 * THE SCOPES AND THE CALENDARS ARE NAMED BEFORE THE READER LEAVES, which is US-CAL-02's own criterion. Asking for
 * consent mints a signed, expiring state parameter, so the request happens when a reader asks to connect rather
 * than when the screen opens, and what comes back is rendered here: what each scope lets syncr do, in the
 * reader's terms, and which calendars are already read.
 *
 * THE CONTINUE CONTROL IS AN ANCHOR WITH AN HREF, not a handler assigning a location. The destination is not known
 * until the request lands, which is exactly the case where a two-step is right: the reader reads what they are
 * agreeing to, then follows a link that keeps middle-click, cmd-click and the browser's own affordances.
 *
 * AN UNCONFIGURED DEPLOYMENT IS NOT AN ERROR HERE. A deployment with no Google client cannot connect an account and
 * says so where the control would be; ICS feeds are unaffected, which the sentence names because a notice that
 * says only what is unavailable leaves a reader unable to decide what to do next. */

import { Panel } from "../../../ui/layout";
import { Button } from "../../../ui/primitives";
import { Refusal } from "./Refusal";
import type { ConsentRequest, GoogleConnection } from "../../../api/hooks/useCalendarSources";

export interface GoogleConsentPanelProps {
  readonly connection: GoogleConnection;
  readonly request: ConsentRequest;
}

export function GoogleConsentPanel({ connection, request }: GoogleConsentPanelProps) {
  if (!connection.configured) {
    return (
      <Panel title="Google">
        <p className="text-base text-ink-soft">
          This deployment has no Google client configured, so no account can be connected. ICS feeds
          still work and are added with the field pair above, and every other part of syncr is
          unaffected.
        </p>
      </Panel>
    );
  }

  const { consent } = request;

  return (
    <Panel
      title="Google"
      headerEnd={<span>{connection.connected ? "connected" : "not connected"}</span>}
    >
      {consent === null ? (
        <>
          <p className="text-base text-ink-soft">
            Connecting names the scopes syncr asks for and the calendars it will read before
            anything is granted.
          </p>
          <div>
            <Button rank="secondary" onClick={() => void request.begin()}>
              {connection.connected ? "Reconnect Google" : "Connect Google"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-base text-ink-soft">{consent.statement}</p>
          <ul>
            {consent.scopes.map((scope) => (
              <li key={scope.scope} className="border-b border-rule py-2 text-sm text-ink">
                {scope.statement}
              </li>
            ))}
          </ul>
          {consent.calendarsRead.length === 0 ? null : (
            <ul>
              {consent.calendarsRead.map((calendar) => (
                <li
                  key={calendar.displayName}
                  className="border-b border-rule py-2 text-sm text-ink"
                >
                  {`${calendar.displayName} \u00b7 ${calendar.included ? "read" : "excluded"}`}
                </li>
              ))}
            </ul>
          )}
          <div>
            <Button asChild rank="secondary">
              <a href={consent.authorizationUrl}>Continue to Google</a>
            </Button>
          </div>
        </>
      )}
      <Refusal problem={request.problem} />
    </Panel>
  );
}
