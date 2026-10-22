import type { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  if (!path.length || path.some((part) => part === ".." || part === ".")) {
    return Response.json({ detail: "Invalid backend path" }, { status: 400 });
  }
  const isHealthPath = path.length === 1 && (path[0] === "health" || path[0] === "metrics");
  const isApiPath = path[0] === "api" && path[1] === "v1";
  if (!isHealthPath && !isApiPath) {
    return Response.json({ detail: "Backend path is not allowed through this proxy" }, { status: 404 });
  }

  const baseUrl = (process.env.VERITYX_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const target = new URL(`${baseUrl}/${path.map(encodeURIComponent).join("/")}`);
  target.search = request.nextUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);

  // Service credentials stay on the Next.js server, never in NEXT_PUBLIC variables.
  const serviceKey = process.env.VERITYX_API_KEY;
  if (serviceKey) headers.set("X-API-Key", serviceKey);

  const suppliedInvestigationToken = request.headers.get("x-investigation-token");
  if (suppliedInvestigationToken) headers.set("X-Investigation-Token", suppliedInvestigationToken);
  const investigationId = request.headers.get("x-investigation-id");
  if (investigationId) headers.set("X-Investigation-ID", investigationId);

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(target, init);
    const responseHeaders = new Headers();
    const upstreamContentType = upstream.headers.get("content-type");
    if (upstreamContentType) responseHeaders.set("content-type", upstreamContentType);
    responseHeaders.set("cache-control", "no-store");
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return Response.json(
      { detail: "Cannot reach the VerityX API. Check VERITYX_BACKEND_URL and ensure the backend is running." },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
