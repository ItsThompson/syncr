/* `shadow_geometry`: the `Interview`, `Exam` and `Lecture` types with their real leads, durations and
 * buffers, as `screens.html` renders them.
 *
 * The three sets of numbers are S33's, and each is here for a case the others cannot make:
 *
 * | Type | Numbers | The case |
 * |---|---|---|
 * | `Interview` | prep 6h lead / 30m, transit 60m lead / 30m, return 0, post 75m `areas` | the worked example: prep at 10:00, transit out at 15:00, no return leg, recovery from the anchor's END |
 * | `Lecture` | `Pre 0m`, transit 30m lead / 30m, return 30m, post 75m | the prep-collision rule must ACCEPT this, and the return leg is exempt from its own anchor's recovery |
 * | `Exam` | prep 14h lead / 30m | a lead crossing a week boundary: prep for a Monday 09:30 anchor falls on the Sunday evening before it, in Sunday's week |
 *
 * The anchors come from `geometry.ics`, whose Wednesday interview is 16:00 to 16:45 and whose Monday
 * exam is 09:30, which are the two the arithmetic above is stated against.
 */

import type { ApiClient } from "../../api/client.ts";
import { ICS_PROVIDER } from "../../config.ts";
import { declareBaseline } from "../baseline.ts";
import { declareAnchorType, declareIcsSource, declareRoutine } from "../declarations.ts";

export const seedShadowGeometry = async (client: ApiClient): Promise<void> => {
  const { areas, templateId } = await declareBaseline(client);

  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "23:00:00",
    durationMinutes: 480,
  });
  // 18:00 is immediately after the Interview's recovery window ends, which is what makes "a Dinner
  // block at 18:00 is legal" an assertion rather than an assumption.
  await declareRoutine(client, templateId, {
    title: "Dinner",
    targetTime: "18:00:00",
    durationMinutes: 30,
  });

  await declareAnchorType(client, {
    name: "Interview",
    matchTitleContains: "Interview",
    prepAreaId: areas.Career!,
    prepLeadMinutes: 360,
    prepDurationMinutes: 30,
    transitAreaId: areas.Fitness!,
    transitLeadMinutes: 60,
    transitDurationMinutes: 30,
    returnTransitMinutes: 0,
    postBufferMinutes: 75,
    postScope: "areas",
    forbiddenAreaIds: [areas.Study!],
  });
  await declareAnchorType(client, {
    name: "Lecture",
    matchTitleContains: "Lecture",
    prepDurationMinutes: 0,
    transitAreaId: areas.Fitness!,
    transitLeadMinutes: 30,
    transitDurationMinutes: 30,
    returnTransitMinutes: 30,
    postBufferMinutes: 75,
    postScope: "areas",
    forbiddenAreaIds: [areas.Study!],
  });
  await declareAnchorType(client, {
    name: "Exam",
    matchTitleContains: "Exam",
    prepAreaId: areas.Career!,
    prepLeadMinutes: 840,
    prepDurationMinutes: 30,
  });

  await declareIcsSource(client, "Interviews and exams", `${ICS_PROVIDER}/geometry.ics`);

  console.log("shadow_geometry: Interview, Lecture and Exam declared over geometry.ics");
};
