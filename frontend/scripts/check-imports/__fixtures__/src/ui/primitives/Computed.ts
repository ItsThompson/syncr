/* Fixture: a specifier assembled at runtime, which is the obvious next step from a backtick.
 *
 * Nothing that reads source can tell what this reaches, so it is refused rather than resolved. A
 * check that silently ignored it would be a check with a documented bypass. */

export async function fetchByAssembly(part: string): Promise<unknown> {
  const module = await import(`../../api/${part}`);
  return module;
}
