/** Edit only a scalar field already present in the stored claim envelope. */
function segments(pointer: string): string[] {
  if (!pointer.startsWith("/") || pointer === "/") throw new Error("This evidence path cannot be edited.");
  const parts = pointer.slice(1).split("/").map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
  if (parts.some((part) => !part || ["__proto__", "prototype", "constructor"].includes(part))) {
    throw new Error("This evidence path cannot be edited.");
  }
  return parts;
}

export function readPointer(claim: unknown, pointer: string): unknown {
  let current = claim;
  for (const part of segments(pointer)) {
    if (!current || typeof current !== "object" || !Object.hasOwn(current, part)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/** Prioritize editable evidence from checks that have not passed. */
export function editableEvidencePaths(
  findings: readonly { status: string; evidence: readonly { path: string }[] }[],
  claim: unknown,
): string[] {
  const paths = new Set<string>();
  for (const finding of findings) {
    if (finding.status === "PASS") continue;
    for (const evidence of finding.evidence) {
      try {
        const value = readPointer(claim, evidence.path);
        if (value === null || typeof value === "string" || typeof value === "number") {
          paths.add(evidence.path);
        }
      } catch {
        // Some evidence is computed rather than a claim field.
      }
    }
  }
  return [...paths];
}

export function updatePointer(text: string, pointer: string, input: string): string {
  const claim = JSON.parse(text) as Record<string, unknown>;
  const path = segments(pointer);
  let parent: unknown = claim;
  for (const part of path.slice(0, -1)) {
    if (!parent || typeof parent !== "object" || !Object.hasOwn(parent, part)) throw new Error("Evidence field is missing from this claim.");
    parent = (parent as Record<string, unknown>)[part];
  }
  const leaf = path.at(-1)!;
  if (!parent || typeof parent !== "object" || !Object.hasOwn(parent, leaf)) throw new Error("Evidence field is missing from this claim.");
  const record = parent as Record<string, unknown>;
  const previous = record[leaf];
  if (previous !== null && typeof previous !== "string" && typeof previous !== "number") throw new Error("This evidence field needs advanced editing.");
  const numeric = typeof previous === "number" || (previous === null && /(?:amount|price|quantity|total)$/i.test(leaf));
  if (numeric) {
    const parsed = input.trim() === "" ? null : Number(input);
    if (parsed !== null && !Number.isFinite(parsed)) throw new Error("Enter a valid number for this field.");
    record[leaf] = parsed;
  } else {
    record[leaf] = input;
  }
  return JSON.stringify(claim, null, 2);
}
