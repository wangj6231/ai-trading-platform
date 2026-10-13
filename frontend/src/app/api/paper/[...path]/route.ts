import { paperProxy } from "@/lib/product/paper-proxy";

type Context = { params: Promise<{ path: string[] }> };
async function handle(request: Request, context: Context) { return paperProxy(request, (await context.params).path); }
export const GET = handle;
export const POST = handle;
export const PATCH = handle;
