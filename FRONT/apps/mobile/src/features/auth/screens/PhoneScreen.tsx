import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { router } from 'expo-router'
import { useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { View } from 'react-native'

import { type PhoneValues, phoneSchema } from '@app/schemas'

import {
  type ChallengeResponse,
  authPhoneConfirm,
  authPhoneStart
} from '@app/api'

import {
  Button,
  FormField,
  Notice,
  Screen,
  SegmentedControl,
  Text
} from '@/components/ui'

import { CodeStep } from '@/features/auth/components/CodeStep'
import { RecoveryCodes } from '@/features/auth/components/RecoveryCodes'
import { describeDestination } from '@/features/auth/model/channels'
import { useAuth } from '@/features/auth/providers/AuthProvider'
import {
  StepUpCancelled,
  useStepUp
} from '@/features/auth/stepUp/StepUpProvider'

import { errorMessage } from '@/lib/errors'

import { createStyles } from '@/theme'

const CHANNELS = [
  { value: 'telegram', label: 'Telegram' },
  { value: 'sms', label: 'SMS' }
] as const

export default function PhoneScreen() {
  const styles = useStyles()
  const { user, refreshUser } = useAuth()
  // Смена номера: сервер сам попросит подтверждение текущим телефоном,
  // приложением или резервным кодом — почта для этого не принимается.
  const changing = !!user?.phone
  const withStepUp = useStepUp()
  const [challenge, setChallenge] = useState<ChallengeResponse | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const form = useForm<PhoneValues>({
    resolver: zodResolver(phoneSchema),
    defaultValues: { phone: '', channel: 'telegram' }
  })
  const send = useMutation({
    mutationFn: (values: PhoneValues) =>
      withStepUp(() =>
        authPhoneStart({
          phone: values.phone,
          channel: values.channel ?? 'telegram'
        })
      ),
    onSuccess: setChallenge
  })
  const channel =
    useWatch({ control: form.control, name: 'channel' }) ?? 'telegram'

  async function finish() {
    await refreshUser()
    router.back()
  }

  const submit = form.handleSubmit(values => send.mutate(values))

  return (
    <Screen
      keyboard
      bottomInset
      logo={false}
    >
      <View style={styles.heading}>
        <Text variant='screenTitle'>
          {changing ? 'Смена номера' : 'Защитите аккаунт'}
        </Text>
        <Text tone='secondary'>
          {changing
            ? `Сейчас привязан ${user?.phone}. Сначала подтвердим, что это вы, затем отправим код на новый номер.`
            : 'Телефон нужен для входа и подтверждения действий с ключом магазина. Пароля и почты для этого недостаточно.'}
        </Text>
      </View>
      {codes ? (
        <RecoveryCodes
          codes={codes}
          onContinue={() => void finish()}
        />
      ) : challenge ? (
        <CodeStep
          destination={describeDestination(challenge)}
          resendAfter={challenge.resend_after}
          onSubmit={async code => {
            const result = await withStepUp(() => authPhoneConfirm({ code }))
            if (result.recovery_codes?.length) setCodes(result.recovery_codes)
            else await finish()
          }}
          onResend={async () =>
            (await send.mutateAsync(form.getValues())).resend_after
          }
        />
      ) : (
        <View style={styles.form}>
          <FormField
            control={form.control}
            name='phone'
            label='Номер телефона'
            placeholder='+7 900 123-45-67'
            keyboardType='phone-pad'
            autoComplete='tel'
            textContentType='telephoneNumber'
          />
          <Text
            variant='label'
            tone='secondary'
          >
            Куда отправить код
          </Text>
          <SegmentedControl
            options={CHANNELS}
            value={channel}
            onChange={channel => form.setValue('channel', channel)}
          />
          {send.error && !(send.error instanceof StepUpCancelled) && (
            <Notice
              tone='error'
              message={errorMessage(send.error)}
            />
          )}
          <Button
            title='Получить код'
            loading={send.isPending}
            onPress={() => void submit()}
          />
        </View>
      )}
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  heading: {
    gap: spacing.sm,
    marginTop: spacing.huge,
    marginBottom: spacing.xl
  },
  form: { gap: spacing.md }
}))
