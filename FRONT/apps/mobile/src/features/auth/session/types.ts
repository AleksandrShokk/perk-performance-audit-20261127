/** Секретные токены доступны приложению; браузер хранит только CSRF-подтверждение. */
export type SessionTokens =
  | { accessToken: string; refreshToken: string; csrfToken?: undefined }
  | { csrfToken: string; accessToken?: undefined; refreshToken?: undefined }
