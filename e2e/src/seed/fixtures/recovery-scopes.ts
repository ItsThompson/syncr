/* `recovery_scopes`: two anchor types, one `post_scope: areas` and one `post_scope: all`, against the
 * same anchor time.
 *
 * The same time on two different days, from one feed, so the only difference between the two
 * recovery windows is the scope. That is what the denominator tests need: a `scope == "all"` window
 * leaves discretionary time and a `scope == "areas"` one does not, and a comparison between two
 * windows at different times of day would be measuring the day rather than the scope.
 *
 * The forbidden Area is Study, so the `areas` window admits a Fitness block and refuses a Study one,
 * which is S32's observation.
 */

import type { ApiClient } from "../../api/client.ts";
import { ICS_PROVIDER } from "../../config.ts";
import { domainConstants } from "../../harness/compose.ts";
import { declareBaseline } from "../baseline.ts";
import {
  declareAnchorType,
  declareIcsSource,
  declareRoutine,
  declareSlot,
} from "../declarations.ts";

export const seedRecoveryScopes = async (client: ApiClient): Promise<void> => {
  const stated = (await domainConstants()).recovery_scopes;
  const { areas, templateId } = await declareBaseline(client);

  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "23:00:00",
    durationMinutes: 480,
  });
  // Both slots sit inside the recovery windows the two types cast, so a placement inside one is
  // something the solve has a reason to attempt.
  await declareSlot(client, templateId, {
    areaId: areas.Study!,
    targetTime: "17:00:00",
    durationMinutes: 60,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Fitness!,
    targetTime: "17:00:00",
    durationMinutes: 60,
  });

  // Wednesday 16:00 to 16:45. Its recovery forbids Study and nothing else.
  await declareAnchorType(client, {
    name: "Interview",
    matchTitleContains: "Interview",
    postBufferMinutes: stated.recoveryMinutes,
    postScope: "areas",
    forbiddenAreaIds: [areas.Study!],
  });
  // Thursday 16:00 to 17:30, the same wall time on a different date. Its recovery forbids everything.
  await declareAnchorType(client, {
    name: "Lecture",
    matchTitleContains: "Lecture",
    postBufferMinutes: stated.recoveryMinutes,
    postScope: "all",
  });

  await declareIcsSource(client, "Interviews and lectures", `${ICS_PROVIDER}/geometry.ics`);

  console.log(
    `recovery_scopes: Interview forbids Study for ${stated.recoveryMinutes} minutes and Lecture ` +
      `forbids everything; a window is labelled like ${stated.label}`,
  );
};
