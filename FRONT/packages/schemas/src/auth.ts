import {
  AuthChangePasswordBody,
  AuthLoginBody,
  AuthMfaVerifyBody,
  AuthPasswordForgotBody,
  AuthPasswordResetBody,
  AuthPhoneStartBody,
  AuthRegisterBody,
  AuthRegisterVerifyBody
} from '@app/api/zod'
import { z } from 'zod'

/**
 * Формы авторизации. Основа — схемы из OpenAPI бэкенда (длины, форматы, каналы);
 * здесь только то, чего нет в API: обрезка email и требования к паролю.
 */
const email = z.string().trim().toLowerCase().pipe(AuthLoginBody.shape.email)

/** Пароль не обрезаем: пробелы могут быть частью парольной фразы. */
const newPassword = AuthRegisterBody.shape.password.refine(
  value => new Set(value).size >= 6,
  'Используйте более разнообразную парольную фразу'
)

/** Одноразовый код из письма, Telegram или SMS. */
export const otpCode = AuthRegisterVerifyBody.shape.code
  .trim()
  .regex(/^\d{6}$/, 'Введите 6 цифр')

/** Сохранённый резервный код: префикс и 22 символа, как на бэке. */
export const recoveryCode = AuthMfaVerifyBody.shape.code
  .trim()
  .regex(
    /^rc_[A-Za-z0-9_-]{22}$/,
    'Введите полный резервный код, начинающийся с rc_'
  )

/** Второй фактор: 6 цифр или резервный код `rc_…`. */
export const secondFactorCode = AuthMfaVerifyBody.shape.code
  .trim()
  .regex(/^(\d{6}|rc_[A-Za-z0-9_-]{8,64})$/, 'Введите 6 цифр или резервный код')

export const signInSchema = AuthLoginBody.pick({ password: true }).extend({
  email
})

export const signUpSchema = AuthRegisterBody.pick({
  workspace_name: true
}).extend({
  email,
  password: newPassword,
  workspace_name: AuthRegisterBody.shape.workspace_name
    .unwrap()
    .trim()
    .min(1, 'Введите название кабинета')
})

export const phoneSchema = AuthPhoneStartBody.extend({
  phone: AuthPhoneStartBody.shape.phone.refine(
    value => value.replace(/\D/g, '').length >= 10,
    'Введите номер телефона полностью'
  )
})

export const forgotPasswordSchema = AuthPasswordForgotBody.extend({ email })

export const resetPasswordSchema = AuthPasswordResetBody.pick({
  new_password: true
}).extend({ new_password: newPassword })

export const changePasswordSchema = AuthChangePasswordBody.extend({
  new_password: newPassword
})

export type ChangePasswordValues = z.infer<typeof changePasswordSchema>
export type SignInValues = z.infer<typeof signInSchema>
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>
export type SignUpValues = z.infer<typeof signUpSchema>
export type PhoneValues = z.input<typeof phoneSchema>
