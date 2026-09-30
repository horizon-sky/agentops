import type { NextConfig } from "next";

// 后端地址：本地默认 8000；线上在 Vercel 环境变量中设为 Railway 域名。
// 通过 rewrite 把 /api/* 代理到后端，前端与后端同源，彻底规避 CORS 配置。
const proxyTarget = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  // 不启用 output: "standalone"：该模式在 Windows 上创建符号链接会 EPERM 失败，
  // 且 Vercel 部署不需要它。Docker 自托管改用「完整 node_modules + pnpm start」方案。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${proxyTarget}/:path*`,
      },
    ];
  },
};

export default nextConfig;
