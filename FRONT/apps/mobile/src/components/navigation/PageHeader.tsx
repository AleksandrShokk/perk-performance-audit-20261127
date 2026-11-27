import { router } from 'expo-router'
import { ArrowLeft } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import { Avatar, Text } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'

import { createStyles, useTheme } from '@/theme'

export function ProfileButton() {
  const { user } = useAuth()
  return (
    <Pressable
      accessibilityRole='button'
      accessibilityLabel='Профиль'
      onPress={() => router.push('/profile')}
    >
      <Avatar name={user?.email ?? ''} />
    </Pressable>
  )
}

export function PageHeading({
  title,
  children
}: {
  title: string
  children?: React.ReactNode
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <View style={styles.row}>
      <Pressable
        accessibilityRole='button'
        accessibilityLabel='Назад'
        style={styles.back}
        onPress={() =>
          router.canGoBack() ? router.back() : router.replace('/(tabs)')
        }
      >
        <ArrowLeft
          size={24}
          color={colors.accent}
        />
      </Pressable>
      <Text
        variant='screenTitle'
        style={styles.title}
      >
        {title}
      </Text>
      {children}
    </View>
  )
}

const useStyles = createStyles(({ spacing, sizes }) => ({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  back: {
    minHeight: sizes.touchTarget,
    minWidth: sizes.touchTarget,
    justifyContent: 'center'
  },
  title: { flex: 1 }
}))
