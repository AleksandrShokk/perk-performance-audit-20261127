/** A single international prefix, including paste/autofill and Russian domestic numbers. */
export function formatPhoneInput(value: string) {
  let digits = value.replace(/\D/g, '')
  if (digits.length === 11 && digits.startsWith('8'))
    digits = '7' + digits.slice(1)
  return '+' + digits.slice(0, 15)
}

export const TELEGRAM_PHONE_NOTICE =
  'Номер должен совпадать с номером вашего аккаунта Telegram.'
