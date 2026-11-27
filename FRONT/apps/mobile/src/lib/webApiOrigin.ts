/** В разработке web и API используют один хост, чтобы браузер принимал cookies. */
export function webApiOrigin(
  configured: string,
  pageURL?: string,
  development = false
) {
  const origin = new URL(
    configured
      .trim()
      .replace(/\/+$/, '')
      .replace(/\/api\/v1$/, '')
  )
  if (
    development &&
    pageURL &&
    ['localhost', '127.0.0.1', '[::1]'].includes(origin.hostname)
  ) {
    const page = new URL(pageURL)
    const local =
      /^(localhost|127\.0\.0\.1|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)$/
    if (local.test(page.hostname)) origin.hostname = page.hostname
  }
  return origin.origin
}
