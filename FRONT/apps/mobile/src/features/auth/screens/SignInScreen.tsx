import { router } from 'expo-router'

import { Button, FormField, Notice } from '@/components/ui'

import { AuthLayout } from '@/features/auth/components/AuthLayout'
import { FooterLink } from '@/features/auth/components/FooterLink'
import { useSignInForm } from '@/features/auth/hooks/useSignInForm'

import { errorMessage } from '@/lib/errors'

export default function SignInScreen() {
  const { control, email, submit, isPending, error } = useSignInForm()

  return (
    <AuthLayout
      title='Вход'
      subtitle='Вся аналитика вашего магазина в одном месте.'
      footer={
        <FooterLink
          text='Нет аккаунта?'
          action='Создать'
          href='/sign-up'
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
        returnKeyType='next'
      />
      <FormField
        control={control}
        name='password'
        label='Пароль'
        secure
        autoComplete='current-password'
        textContentType='password'
        returnKeyType='go'
        onSubmitEditing={submit}
      />
      {error && (
        <Notice
          tone='error'
          message={errorMessage(error)}
        />
      )}
      <Button
        title='Войти'
        loading={isPending}
        onPress={submit}
      />
      <Button
        variant='ghost'
        title='Забыли пароль?'
        onPress={() =>
          router.push({ pathname: '/forgot-password', params: { email } })
        }
      />
    </AuthLayout>
  )
}
