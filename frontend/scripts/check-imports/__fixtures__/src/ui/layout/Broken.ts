/* Fixture: an import that resolves to nothing, which the bundler would fail on later. */

import { gone } from "./Vanished";

export const value = gone;
