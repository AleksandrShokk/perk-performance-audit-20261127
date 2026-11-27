import { Stack } from 'expo-router'

import { useTheme } from '@/theme'

export const unstable_settings = { anchor: 'sign-in' }

export default function AuthLayout() {
  const { colors } = useTheme()
  return (
    <Stack
      screenOptions={{
        headerTransparent: true,
        headerTitle: '',
        headerShadowVisible: false,
        headerBackButtonDisplayMode: 'minimal',
        headerTintColor: colors.accent
      }}
    >
      <Stack.Screen
        name='sign-in'
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name='sign-up'
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name='forgot-password'
        options={{ headerShown: false }}
      />
    </Stack>
  )
}
