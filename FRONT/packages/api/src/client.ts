import { type AxiosError, type AxiosRequestConfig, create } from 'axios'

/**
 * Единственный HTTP-клиент приложения. Приложение задаёт адрес и перехватчики
 * (авторизация, обновление сессии) через `http`; сгенерированный код вызывает `apiClient`.
 */
export const http = create({ timeout: 15_000 })

export function configureApi(baseURL: string) {
  http.defaults.baseURL = baseURL
}

export function apiClient<T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig
): Promise<T> {
  return http<T>({ ...config, ...options }).then(({ data }) => data)
}

/** Тело ошибки API: прежний `detail` плюс `code`, `message`, `request_id`. */
export type ApiErrorBody = {
  detail?: unknown
  code?: string
  message?: string
  request_id?: string
}

export type ErrorType<Error = ApiErrorBody> = AxiosError<Error>
export type BodyType<Body> = Body
