import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `standalone` traces the server's actual module graph and emits it plus a
  // minimal `server.js`. Without it the runtime stage would have to carry the
  // whole of node_modules, which is most of the image for none of the benefit.
  output: "standalone",

  // The build must fail on a type error or a lint error. Next's defaults already
  // do this; stating it means a future `ignoreBuildErrors` cannot be added
  // quietly as a way past a red build.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },

  reactStrictMode: true,

  // The container serves the app; it does not need to advertise which server.
  poweredByHeader: false,
};

export default nextConfig;
