/** Select a beta tag without modifying git or reserving a release number. */
export function betaTagName(tags: string[], core: string): string {
  if (!/^\d+\.\d+\.\d+$/.test(core)) {
    throw new Error("Expected a release train X.Y.Z");
  }
  const pattern = new RegExp(`^v${core.replaceAll(".", "\\.")}-beta\\.(\\d+)$`);
  const numbers = tags.map((tag) => pattern.exec(tag)).filter((m) => m !== null)
    .map((m) => Number(m![1]));
  return `v${core}-beta.${Math.max(0, ...numbers) + 1}`;
}

export function requireExpectedTag(actual: string, expected?: string): void {
  if (expected && actual !== expected) {
    throw new Error(
      `Beta tags changed: planned ${expected}, next tag is ${actual}. Retry the release.`,
    );
  }
}
