import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  // 不启用 output: "standalone"：该模式在 Windows 上创建符号链接会 EPERM 失败，
  // 且 Vercel 部署不需要它。Docker 自托管改用「完整 node_modules + pnpm start」方案。
};

export default nextConfig;
