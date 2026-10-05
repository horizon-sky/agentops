import { handleAuth } from "@/lib/server/auth";

export const POST = (request: Request) => handleAuth(request, "logout");
