/* The Areas a tenant has declared, and how much of the sealed ramp they are using.
 *
 * The ramp reading travels with the list because it is a fact about the list rather than about any one
 * Area: `statement` is non-null exactly when two Areas hold one step of the ramp, which is what a
 * thirteenth Area produces. A surface that renders Area chips has to say so, because past twelve the
 * pigment repeats and the chip alone stops identifying anything. Dropping the reading here would make
 * that unsayable on every screen at once. */

import useSWR from "swr";

import { client } from "../client";
import { areasKey } from "../keys";
import { read } from "./request";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Area = components["schemas"]["AreaResponse"];
export type Ramp = components["schemas"]["RampReading"];

export interface Areas {
  readonly areas: readonly Area[];
  readonly ramp: Ramp;
}

async function readAreas(): Promise<Areas> {
  const { areas, ramp } = await read(() => client.GET("/api/v1/areas"));
  return { areas, ramp };
}

export function useAreas(): Resource<Areas> {
  return toResource(useSWR<Areas, Problem>(areasKey(), readAreas));
}
