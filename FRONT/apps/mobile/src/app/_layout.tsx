import { focusManager } from '@tanstack/react-query'
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client'
import { Stack, ThemeProvider, router } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { useEffect } from 'react'
import { AppState, Platform } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { configureValidationMessages } from '@app/schemas'

import { Button, Logo, Notice, Screen } from '@/components/ui'

import { AuthProvider, useAuth } from '@/features/auth/providers/AuthProvider'
import { StepUpProvider } from '@/features/auth/stepUp/StepUpProvider'
import { ProductDisplayProvider } from '@/features/products/providers/ProductDisplayProvider'
import {
  PendingInviteProvider,
  usePendingInvite
} from '@/features/team/providers/PendingInviteProvider'
import {
  WorkspaceProvider,
  useWorkspace
} from '@/features/workspace/providers/WorkspaceProvider'

import { setupHttp } from '@/lib/http'
import { persistOptions, queryClient } from '@/lib/queryClient'

import { createStyles, navigationTheme, useTheme } from '@/theme'

// При завершении сессии защищённый стек возвращается в группу входа.
export const unstable_settings = { anchor: '(auth)' }

setupHttp()
configureValidationMessages()

export default function RootLayout() {
  const styles = useStyles()
  const theme = useTheme()
  useEffect(() => {
    if (Platform.OS === 'web') return
    focusManager.setFocused(AppState.currentState === 'active')
    const subscription = AppState.addEventListener('change', state => {
      focusManager.setFocused(state === 'active')
    })
    return () => subscription.remove()
  }, [])
  return (
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <ThemeProvider value={navigationTheme(theme)}>
          <StatusBar style={theme.isDark ? 'light' : 'dark'} />
          <PersistQueryClientProvider
            client={queryClient}
            persistOptions={persistOptions}
          >
            <PendingInviteProvider>
              <AuthProvider>
                <ProductDisplayProvider>
                  <WorkspaceProvider>
                    <StepUpProvider>
                      <AuthNavigator />
                    </StepUpProvider>
                  </WorkspaceProvider>
                </ProductDisplayProvider>
              </AuthProvider>
            </PendingInviteProvider>
          </PersistQueryClientProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  )
}

function AuthNavigator() {
  const { status, refreshUser, signOut } = useAuth()
  const { colors } = useTheme()
  const invite = usePendingInvite()
  const { isAdmin, status: workspaceStatus } = useWorkspace()
  useEffect(() => {
    if (status === 'signedIn' && invite.ready && invite.code)
      router.replace('/invite')
  }, [status, invite.ready, invite.code])
  if (!invite.ready || status === 'restoring')
    return (
      <Screen
        logo={false}
        scroll={false}
        contentStyle={{ justifyContent: 'center', alignItems: 'center' }}
      >
        <Logo height={40} />
      </Screen>
    )
  if (status === 'offline')
    return (
      <Screen>
        <Notice
          title='Не удалось проверить сессию'
          message='Проверьте соединение с сервером и повторите попытку.'
          actionTitle='Повторить'
          onAction={() => void refreshUser()}
        />
        <Button
          title='Выйти из аккаунта'
          variant='ghost'
          onPress={signOut}
        />
      </Screen>
    )
  // У группы (auth) нет index: для закрытых экранов нужен адрес формы входа.
  const redirectTo =
    status === 'signedOut'
      ? '/sign-in'
      : status === 'secondFactor'
        ? '/second-factor'
        : invite.code
          ? '/invite'
          : '/(tabs)'

  return (
    <Stack
      screenOptions={{
        headerTitle: '',
        headerTintColor: colors.accent,
        headerBackButtonDisplayMode: 'minimal',
        headerShadowVisible: false,
        headerTransparent: true
      }}
    >
      <Stack.Screen
        name='invite'
        options={{ headerShown: false }}
      />
      <Stack.Protected
        guard={status === 'signedOut'}
        redirectTo={redirectTo}
      >
        <Stack.Screen
          name='(auth)'
          options={{ headerShown: false }}
        />
      </Stack.Protected>
      <Stack.Protected
        guard={status === 'secondFactor'}
        redirectTo={redirectTo}
      >
        <Stack.Screen
          name='second-factor'
          options={{ headerShown: false }}
        />
      </Stack.Protected>
      <Stack.Protected
        guard={status === 'signedIn'}
        redirectTo={redirectTo}
      >
        <Stack.Screen
          name='(tabs)'
          options={{ headerShown: false }}
        />
        <Stack.Screen name='profile' />
        <Stack.Screen name='change-password' />
        <Stack.Protected guard={isAdmin || workspaceStatus !== 'ready'}>
          <Stack.Screen name='team' />
          <Stack.Screen name='stores' />
          <Stack.Screen name='stores/[storeId]' />
        </Stack.Protected>
        <Stack.Screen name='phone' />
        <Stack.Screen name='connect-store' />
        <Stack.Screen name='reports/[topic]' />
        <Stack.Screen
          name='supplies'
          options={{ headerShown: false }}
        />
        <Stack.Screen
          name='inventory/products'
          options={{ headerShown: false }}
        />
      </Stack.Protected>
    </Stack>
  )
}

const useStyles = createStyles(({ colors }) => ({
  root: { flex: 1, backgroundColor: colors.background.screen }
}))
