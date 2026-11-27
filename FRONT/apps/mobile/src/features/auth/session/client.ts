/** Нативное приложение получает токены; браузер использует HttpOnly cookies. */
export function getAuthClient(): 'mobile' | 'web' {
  return 'mobile'
}
