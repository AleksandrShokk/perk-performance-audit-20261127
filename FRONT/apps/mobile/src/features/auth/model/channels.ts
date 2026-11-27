import type { ChallengeResponse } from '@app/api'

export type CodeChannel = ChallengeResponse['channel']

const PLACE: Record<CodeChannel, string> = {
  email: 'на почту',
  telegram: 'в Telegram',
  sms: 'по SMS'
}

/** «в Telegram на +7 *** ***-45-67» — для подписи над полем кода. */
export function describeDestination({
  channel,
  destination
}: Pick<ChallengeResponse, 'channel' | 'destination'>) {
  return `${PLACE[channel]} ${destination}`
}

export const CHANNEL_LABELS: Record<CodeChannel, string> = {
  email: 'Почта',
  telegram: 'Telegram',
  sms: 'SMS'
}

/** Причина сбоя автоматической доставки из ответа входа. */
export function codeDeliveryMessage(code: string | null | undefined) {
  if (code === 'otp_throttled')
    return 'Отправка кода временно ограничена. Дождитесь окончания таймера перед повторной отправкой.'
  if (code === 'telegram_unavailable')
    return 'Не удалось доставить код в Telegram. Повторите позже или выберите другой доступный способ.'
  if (code === 'sms_unavailable')
    return 'Не удалось доставить код по SMS. Повторите позже или выберите другой доступный способ.'
  return 'Код не удалось отправить автоматически. Повторите отправку после окончания таймера.'
}
