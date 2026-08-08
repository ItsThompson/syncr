#!/usr/bin/env node
/* Load one fixture into the e2e stack, from nothing.
 *
 *   node e2e/src/seed/cli.ts reference_week
 *
 * Four steps, always in this order and always all four: empty the database, provision the tenant
 * through the console script a first deployment runs, declare the fixture over the HTTP API, and then
 * materialize by ticking the plan-horizon maintainer.
 *
 * SELF-CONTAINED, BECAUSE A PROBE RECIPE THAT NEEDS A SECOND COMMAND IS A RECIPE THAT GETS RUN WRONG.
 * The alternative was a `just` recipe with four lines, which would have put the ordering in a file no
 * test reads and made the ordering itself a thing to remember: the tick must follow the declarations,
 * or the week is planned before there is anything to plan.
 *
 * IT MATERIALIZES AND DOES NOT SOLVE. Materializing is what the product does unprompted; solving is
 * what a scenario asks for, and several of them are ABOUT the first solve. So the seed leaves every
 * week in the state the maintainer leaves it in, and a scenario that wants a solved week says so.
 */

import { fixtureNames } from "./fixtures.ts";
import { loadFixture } from "./load.ts";

const [name] = process.argv.slice(2);

if (!name) {
  console.error(`name a fixture. The fixtures are: ${fixtureNames().join(", ")}`);
  process.exit(2);
}

const { log } = await loadFixture(name);
for (const line of log) console.log(line);
