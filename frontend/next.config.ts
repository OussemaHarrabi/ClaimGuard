import type { NextConfig } from "next";

/**
 * The cockpit reaches the review API through `src/app/v1/[...path]/route.ts`,
 * which reads `CLAIMGUARD_API_ORIGIN` at request time. That is deliberate: a
 * `rewrites()` entry here would be resolved while BUILDING, baking one API
 * address into the bundle and ignoring the variable when the server starts.
 *
 * `NEXT_PUBLIC_*` values ARE still build-time - that is a Next.js rule for
 * anything inlined into the browser bundle - so the reviewer name and demo mode
 * belong in the build (or in the container's build args).
 */
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
