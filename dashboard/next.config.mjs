/** @type {import('next').NextConfig} */
const rawApiProxyTarget =
  process.env.API_PROXY_TARGET ||
  process.env.NEXT_PUBLIC_API_PROXY_TARGET ||
  "http://127.0.0.1:8000";
const apiProxyTarget = rawApiProxyTarget.replace(/\/+$/, "");

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
