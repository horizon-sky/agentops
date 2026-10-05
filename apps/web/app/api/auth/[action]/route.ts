import { handleAuth } from "@/lib/server/auth";

export async function POST(request: Request, context: { params: Promise<{ action: string }> }) {
  return handleAuth(request, (await context.params).action);
}
