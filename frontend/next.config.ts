import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  /* config options here */
  output: "standalone",
  reactCompiler: true,
  experimental: {
    useTypeScriptCli: true,
  },
  // Pages merged in the navigation revamp. Kept as permanent redirects so old
  // bookmarks and notification links still land somewhere sensible.
  async redirects() {
    return [
      { source: "/board", destination: "/tasks?view=board", permanent: true },
      { source: "/digest", destination: "/dashboard", permanent: true },
      { source: "/profile", destination: "/settings", permanent: true },
      { source: "/simulator", destination: "/record", permanent: true },
    ];
  },
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
