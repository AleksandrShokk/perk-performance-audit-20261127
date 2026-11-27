import { z } from 'zod'
import ru from 'zod/v4/locales/ru.js'

function unit(origin: string) {
  if (origin === 'string') return ' символов'
  if (origin === 'array') return ' элементов'
  return ''
}

/**
 * Русские сообщения для всех Zod-схем, включая сгенерированные из OpenAPI.
 * Вызывается один раз при запуске приложения.
 */
export function configureValidationMessages() {
  z.config({
    ...ru(),
    customError: issue => {
      switch (issue.code) {
        case 'invalid_type':
          return issue.input === undefined || issue.input === null
            ? 'Заполните поле'
            : 'Проверьте значение'
        case 'too_small':
          if (issue.origin === 'string' && Number(issue.minimum) <= 1)
            return 'Заполните поле'
          return `Не меньше ${issue.minimum}${unit(issue.origin)}`
        case 'too_big':
          return `Не больше ${issue.maximum}${unit(issue.origin)}`
        case 'invalid_format':
          return issue.format === 'email'
            ? 'Введите корректный email'
            : 'Проверьте формат'
        case 'invalid_value':
          return 'Выберите один из вариантов'
        default:
          return undefined
      }
    }
  })
}
