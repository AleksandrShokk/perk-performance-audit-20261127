import { type Href, Link } from 'expo-router'
import { View } from 'react-native'

import { Text } from '@/components/ui'

import { createStyles } from '@/theme'

type FooterLinkProps = { text: string; action: string; href: Href }

/** «Нет аккаунта? Создать» — переход между входом и регистрацией. */
export function FooterLink({ text, action, href }: FooterLinkProps) {
  const styles = useStyles()
  return (
    <View style={styles.row}>
      <Text tone='secondary'>{text}</Text>
      <Link
        href={href}
        replace
        accessibilityRole='link'
      >
        <Text
          tone='accent'
          variant='bodyStrong'
        >
          {action}
        </Text>
      </Link>
    </View>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  row: { flexDirection: 'row', gap: spacing.xxs, alignItems: 'center' }
}))
