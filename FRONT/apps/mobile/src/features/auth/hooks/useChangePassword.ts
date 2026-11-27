import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'

import { type ChangePasswordValues, changePasswordSchema } from '@app/schemas'

import { authChangePassword } from '@app/api'

import { session } from '../session'
import { useStepUp } from '../stepUp/StepUpProvider'

export function useChangePassword() {
  const withStepUp = useStepUp()
  const form = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { password: '', new_password: '' }
  })
  const change = useMutation({
    mutationFn: (values: ChangePasswordValues) =>
      withStepUp(() => authChangePassword(values)),
    // Сервер уже отозвал все устройства: локальные токены и отчёты тоже удаляем.
    onSuccess: () => session.end()
  })
  return {
    control: form.control,
    submit: form.handleSubmit(values => change.mutate(values)),
    pending: change.isPending,
    error: change.error
  }
}
