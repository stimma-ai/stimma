import { betaTagName, requireExpectedTag } from "../release-tags.ts";

Deno.test("beta planning chooses the next number on the selected train", () => {
  const actual = betaTagName([
    "v1.2.3-beta.2",
    "v1.2.3-beta.10",
    "v1.2.4-beta.99",
    "v1.2.30-beta.99",
    "v1.2.3-alpha.100",
    "v1.2.3",
  ], "1.2.3");
  if (actual !== "v1.2.3-beta.11") throw new Error(actual);
  if (betaTagName([], "1.2.3") !== "v1.2.3-beta.1") {
    throw new Error("Expected first beta");
  }
});

Deno.test("a concurrent beta tag cannot silently change the built version", () => {
  requireExpectedTag("v1.2.3-beta.2", "v1.2.3-beta.2");
  requireExpectedTag("v1.2.3-beta.2");
  try {
    requireExpectedTag("v1.2.3-beta.3", "v1.2.3-beta.2");
  } catch (error) {
    if (String(error).includes("Beta tags changed")) return;
    throw error;
  }
  throw new Error("Changed release version was accepted");
});

Deno.test("beta planning rejects malformed release trains", () => {
  for (const core of ["1.2", "1.2.3-beta.1", "1x2x3", "1.2.3;touch file"]) {
    let rejected = false;
    try {
      betaTagName([], core);
    } catch {
      rejected = true;
    }
    if (!rejected) throw new Error(`Accepted ${core}`);
  }
});
