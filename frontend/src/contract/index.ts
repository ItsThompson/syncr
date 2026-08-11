/* The wire contract the kit renders from, kept OUT of `api/`.
 *
 * `api/` is the fetching layer: the client, the key registry, the hooks, and the generated schema.
 * Section 16 declares exactly that set. These two modules were mine and did not belong there, and
 * their being there is what forced the kit's import fence to enumerate specifiers instead of denying
 * a directory. Three times a rule written that way grew a hole.
 *
 * Now every zone rule denies a whole directory and this is the one directory a `domain` component
 * may read. A `Problem` and a `Resource` are domain concepts: a component renders `problem.detail`
 * and switches on `resource.status`. Nothing here fetches. */

export {
  NOTHING_SELECTED_PROBLEM_TYPE,
  UNEXPECTED_PROBLEM_TYPE,
  UNREACHABLE_PROBLEM_TYPE,
  toProblem,
  unreachableProblem,
  type Problem,
} from "./problem";
export { toResource, type Resource } from "./resource";
