import { redirect } from "next/navigation";
import AuthGate from "@/components/AuthGate";
import TopNav from "@/components/TopNav";
import { currentUser } from "@/lib/server/auth";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const user = await currentUser();
  if (!user) redirect("/login");
  return (
    <AuthGate user={user}>
      <TopNav />
      <div className="workspace-content mx-auto max-w-[1600px] px-6 pb-8 pt-[88px]">{children}</div>
    </AuthGate>
  );
}
