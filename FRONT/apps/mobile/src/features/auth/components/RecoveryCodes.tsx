import * as Clipboard from 'expo-clipboard'
import * as Haptics from 'expo-haptics'
import { Check, Copy } from 'lucide-react-native'
import { useEffect, useRef, useState } from 'react'
import { View } from 'react-native'

import { Button, Card, Notice, Text } from '@/components/ui'

import { createStyles } from '@/theme'

type Props = { codes: string[]; onContinue: () => void }

/** Все коды копируются одним нажатием, каждый — с новой строки. */
export function RecoveryCodes({ codes, onContinue }: Props) {
  const styles = useStyles()
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  const copyAll = async () => {
    setCopyError(false)
    setCopied(false)
    try {
      if (!(await Clipboard.setStringAsync(codes.join('\n'))))
        throw new Error('clipboard_unavailable')
      void Haptics.notificationAsync(
        Haptics.NotificationFeedbackType.Success
      ).catch(() => {})
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopyError(true)
    }
  }

  return (
    <View style={styles.container}>
      <Notice
        title='Сохраните резервные коды'
        message='Каждый код одноразовый. Сохраните список.'
      />
      <Card style={styles.codes}>
        {codes.map(code => (
          <View
            key={code}
            style={styles.code}
          >
            <Text
              variant='label'
              tabular
            >
              {code}
            </Text>
          </View>
        ))}
      </Card>
      <Button
        variant='secondary'
        title={copied ? 'Все коды скопированы' : 'Скопировать все коды'}
        icon={copied ? Check : Copy}
        onPress={() => void copyAll()}
      />
      {copyError && (
        <Notice
          tone='error'
          message='Не удалось скопировать. Попробуйте ещё раз.'
        />
      )}
      <Button
        variant='secondary'
        title={saved ? 'Коды сохранены ✓' : 'Я сохранил резервные коды'}
        onPress={() => setSaved(true)}
      />
      <Button
        title='Продолжить'
        disabled={!saved}
        onPress={onContinue}
      />
    </View>
  )
}

const useStyles = createStyles(({ sizes, spacing }) => ({
  container: { gap: spacing.md },
  codes: { gap: spacing.xxs },
  code: {
    minHeight: sizes.touchTarget,
    justifyContent: 'center',
    paddingHorizontal: spacing.xs
  }
}))
