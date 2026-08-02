/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },

  // The app shipped with no security headers at all, which meant any site
  // could embed it in an invisible iframe and trick a logged-in user into
  // clicking things (clickjacking). These are the standard defensive set.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // Nothing here is meant to be embedded anywhere.
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          // Stop browsers guessing a response is a different content type than
          // it says (a classic way to get a text file executed as script).
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Don't leak the full URL of our pages to third-party sites.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // No page here needs the camera, mic or location.
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // Once a browser has seen this, it refuses to talk to us over plain
          // HTTP for a year — protects against downgrade on public wifi.
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
