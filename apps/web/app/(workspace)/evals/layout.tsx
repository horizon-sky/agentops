import { currentUser } from "@/lib/server/auth";

export default async function EvalLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  if (user?.role !== "admin") return <p role="alert">评测看板仅管理员可访问。</p>;
  return children;
}
