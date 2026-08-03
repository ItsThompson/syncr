/* THE LAYER-AGNOSTIC HALF OF THE KEYBOARD, which is everything except the screen chords.
 *
 * `useScreenChords` resolves against the shell's screen table, so it reaches `ui/domain` and the zone rule
 * correctly refuses it from `primitives` and `layout`. It is therefore NOT re-exported here: a barrel that
 * laundered it would make this whole module unreachable from the two lower layers, and `useKeyBinding` and
 * `isTyping` are genuinely layer-agnostic. The shell imports the chord hook from its own module. */

export { isTyping } from "./typing";
export {
  hasPlatformModifier,
  isApplePlatform,
  useKeyBinding,
  type KeyBinding,
} from "./useKeyBinding";
