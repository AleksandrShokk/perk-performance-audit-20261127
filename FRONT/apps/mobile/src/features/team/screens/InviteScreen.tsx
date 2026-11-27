import { useMutation } from '@tanstack/react-query'
import * as Linking from 'expo-linking'
import { router } from 'expo-router'
import { Platform, View } from 'react-native'

import { teamAcceptInvite } from '@app/api'

import {
  Button,
  Card,
  Notice,
  Screen,
  Skeleton,
  Text
} from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import { ROLE_LABELS, inviteAppURL } from '../model/permissions'
import { usePendingInvite } from '../providers/PendingInviteProvider'

import { createStyles } from '@/theme'

export default function InviteScreen() {
  const styles = useStyles()
  const invite = usePendingInvite()
  const pageURL = Linking.useLinkingURL()
  const { user, status, signOut } = useAuth()
  const { selectWorkspace } = useWorkspace()
  const accept = useMutation({
    mutationFn: () => teamAcceptInvite({ code: invite.code! }),
    onSuccess: async result => {
      await selectWorkspace(result.workspace_id)
      invite.clear()
      router.replace('/(tabs)')
    }
  })
  const close = () => {
    invite.clear()
    router.replace(status === 'signedIn' ? '/(tabs)' : '/sign-in')
  }
  const signedIn = status === 'signedIn'
  const wrongEmail =
    signedIn &&
    user?.email.toLowerCase() !== invite.details?.email.toLowerCase()

  return (
    <Screen bottomInset>
      <View style={styles.body}>
        <Text variant='screenTitle'>Приглашение в команду</Text>
        {!invite.ready || invite.pending ? (
          <Skeleton height={180} />
        ) : !invite.code || invite.error ? (
          <Notice
            tone='error'
            message={
              invite.error
                ? errorMessage(invite.error)
                : 'Откройте ссылку из письма.'
            }
          />
        ) : (
          invite.details && (
            <Card>
              <Text variant='sectionTitle'>
                {invite.details.workspace_name}
              </Text>
              <Text>{invite.details.email}</Text>
              <Text tone='secondary'>{ROLE_LABELS[invite.details.role]}</Text>
            </Card>
          )
        )}
        {invite.details &&
          !invite.error &&
          (!signedIn ? (
            <>
              <Button
                title={status === 'secondFactor' ? 'Подтвердить вход' : 'Войти'}
                onPress={() =>
                  router.push(
                    status === 'secondFactor' ? '/second-factor' : '/sign-in'
                  )
                }
              />
              {status === 'signedOut' && (
                <Button
                  title='Зарегистрироваться'
                  variant='secondary'
                  onPress={() => router.push('/sign-up')}
                />
              )}
            </>
          ) : wrongEmail ? (
            <>
              <Notice
                message={`Приглашение отправлено на ${invite.details.email}. Войдите с этим адресом.`}
              />
              <Button
                title='Войти в другой аккаунт'
                onPress={() => void signOut()}
              />
            </>
          ) : !user?.phone ? (
            <Button
              title='Подтвердить номер телефона'
              onPress={() => router.push('/phone')}
            />
          ) : (
            <Button
              title='Принять приглашение'
              loading={accept.isPending}
              onPress={() => accept.mutate()}
            />
          ))}
        {accept.error && (
          <Notice
            tone='error'
            message={errorMessage(accept.error)}
          />
        )}
        {Platform.OS === 'web' && invite.code && (
          <Button
            title={__DEV__ ? 'Открыть в Expo Go' : 'Открыть в приложении'}
            variant='ghost'
            onPress={() =>
              void Linking.openURL(
                inviteAppURL(
                  pageURL ?? 'http://localhost:8081/invite',
                  invite.code!,
                  __DEV__
                )
              ).catch(() => {})
            }
          />
        )}
        <Button
          title='Закрыть приглашение'
          variant='ghost'
          onPress={close}
        />
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  body: { gap: spacing.lg, marginTop: spacing.xxl }
}))
