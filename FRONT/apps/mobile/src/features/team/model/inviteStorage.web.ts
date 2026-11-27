const KEY = 'perk.pending-invite'
export async function readInvite() {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}
export async function saveInvite(code: string) {
  try {
    sessionStorage.setItem(KEY, code)
  } catch {
    /* Ссылка остаётся в памяти текущего экрана. */
  }
}
export async function deleteInvite() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* Хранилище может быть отключено. */
  }
}
