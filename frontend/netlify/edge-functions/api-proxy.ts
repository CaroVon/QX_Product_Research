/**
 * Netlify Edge Function —— API 代理
 * 将 /api/* 请求转发到 BACKEND_URL 环境变量指定的后端服务
 *
 * 在 Netlify UI → Site configuration → Environment variables 中设置:
 *   BACKEND_URL = https://your-backend-server.com
 */
export default async function handler(request: Request) {
  const backend = Deno.env.get("BACKEND_URL")

  if (!backend) {
    return new Response(
      JSON.stringify({ detail: "BACKEND_URL environment variable is not configured on Netlify" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    )
  }

  // 重写目标 URL：把 /api/v1/xxx → https://backend.com/api/v1/xxx
  const url = new URL(request.url)
  const target = new URL(backend)
  url.host = target.host
  url.protocol = target.protocol
  if (target.port) url.port = target.port

  // 重建 Headers：替换 Host 为目标后端，避免 Cloudflare Tunnel 因 Host 不匹配拒绝请求
  const headers = new Headers(request.headers)
  headers.set("Host", target.host)

  const proxyRequest = new Request(url, {
    method: request.method,
    headers,
    body: request.body,
  })

  try {
    return await fetch(proxyRequest)
  } catch (error) {
    return new Response(
      JSON.stringify({
        detail: `Proxy error: ${error instanceof Error ? error.message : String(error)}`,
      }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    )
  }
}
