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
  // port 如果没显式指定（如 https 默认 443）则不加
  if (target.port) url.port = target.port

  // 克隆请求（保留 method / headers / body），只改 URL
  const proxyRequest = new Request(url, request)

  return fetch(proxyRequest)
}
