import type { ReactNode } from 'react'
import { View } from 'react-native'

import { Screen, Text } from '@/components/ui'

import { createStyles } from '@/theme'

type AuthLayoutProps = {
  title: string
  subtitle?: string
  children: ReactNode
  /** Нижняя ссылка: «Нет аккаунта? Создать». */
  footer?: ReactNode
}

export function AuthLayout({ title, children, footer }: AuthLayoutProps) {
  const styles = useStyles()
  return (
    <Screen
      keyboard
      bottomInset
    >
      <View style={styles.body}>
        <Text
          variant='screenTitle'
          align='center'
        >
          {title}
        </Text>
        {children}
        {footer && <View style={styles.footer}>{footer}</View>}
      </View>
    </Screen>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  body: {
    flex: 1,
    justifyContent: 'center',
    gap: spacing.sm
  },
  footer: { alignItems: 'center', paddingTop: spacing.xl }
}))
