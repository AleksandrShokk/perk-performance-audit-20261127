import { Button, FormField, Notice } from '@/components/ui'

import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { FooterLink } from '@/features/auth/components/FooterLink'
import { useSignUpForm } from '@/features/auth/hooks/useSignUpForm'
import { usePendingInvite } from '@/features/team/providers/PendingInviteProvider'

import { errorMessage } from '@/lib/errors'

export default function SignUpScreen() {
  const { control, submit, isPending, error } = useSignUpForm()
  const invite = usePendingInvite()

  return (
    <AuthLayout
      title='Создать аккаунт'
      subtitle='Подтвердим почту кодом, затем подключим магазин Wildberries.'
      footer={
        <FooterLink
          text='Уже есть аккаунт?'
          action='Войти'
          href='/sign-in'
        />
      }
    >
      <FormField
        control={control}
        name='email'
        label='Email'
        placeholder='seller@example.ru'
        keyboardType='email-address'
        autoCapitalize='none'
        autoComplete='email'
        textContentType='emailAddress'
      />
      <FormField
        control={control}
        name='password'
        label='Пароль'
        hint='От 15 символов'
        secure
        autoComplete='new-password'
        textContentType='newPassword'
      />
      {!invite.code && (
        <FormField
          control={control}
          name='workspace_name'
          label='Название кабинета'
          placeholder='Например, Мотосклад'
          autoCapitalize='sentences'
          returnKeyType='go'
          onSubmitEditing={submit}
        />
      )}
      {error && (
        <Notice
          tone='error'
          message={errorMessage(error)}
        />
      )}
      <Button
        title='Продолжить'
        loading={isPending}
        onPress={submit}
      />
    </AuthLayout>
  )
}
