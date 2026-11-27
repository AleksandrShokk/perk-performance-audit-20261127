import { Eye, EyeOff } from 'lucide-react-native'
import { type Ref, useState } from 'react'
import {
  Pressable,
  TextInput,
  type TextInputInstance,
  type TextInputProps,
  View
} from 'react-native'

import { Text } from './Text'
import { createStyles, useTheme } from '@/theme'

export type TextFieldProps = Omit<TextInputProps, 'style'> & {
  label: string
  error?: string
  hint?: string
  /** Поле пароля с кнопкой «показать». */
  secure?: boolean
  ref?: Ref<TextInputInstance>
}

export function TextField({
  label,
  error,
  hint,
  secure = false,
  ref,
  onFocus,
  onBlur,
  ...props
}: TextFieldProps) {
  const styles = useStyles()
  const { colors } = useTheme()
  const [focused, setFocused] = useState(false)
  const [hidden, setHidden] = useState(secure)
  const VisibilityIcon = hidden ? Eye : EyeOff

  return (
    <View style={styles.field}>
      <Text
        variant='labelStrong'
        tone='secondary'
      >
        {label}
      </Text>
      <View
        style={[
          styles.control,
          focused && styles.focused,
          !!error && styles.invalid
        ]}
      >
        <TextInput
          ref={ref}
          placeholderTextColor={colors.text.secondary}
          selectionColor={colors.accent}
          secureTextEntry={hidden}
          accessibilityLabel={label}
          accessibilityHint={error ?? hint}
          {...props}
          style={styles.input}
          onFocus={event => {
            setFocused(true)
            onFocus?.(event)
          }}
          onBlur={event => {
            setFocused(false)
            onBlur?.(event)
          }}
        />
        {secure && (
          <Pressable
            accessibilityRole='button'
            accessibilityLabel={hidden ? 'Показать пароль' : 'Скрыть пароль'}
            hitSlop={14}
            onPress={() => setHidden(value => !value)}
          >
            <VisibilityIcon
              size={20}
              color={colors.text.secondary}
            />
          </Pressable>
        )}
      </View>
      {(error || hint) && (
        <Text
          variant='caption'
          tone={error ? 'error' : 'secondary'}
        >
          {error ?? hint}
        </Text>
      )}
    </View>
  )
}

const useStyles = createStyles(
  ({ colors, radius, sizes, spacing, typography }) => ({
    field: { gap: spacing.xs },
    control: {
      minHeight: sizes.control,
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.md,
      borderRadius: radius.control,
      borderWidth: 1,
      borderColor: colors.border,
      backgroundColor: colors.background.card
    },
    focused: {
      borderColor: colors.accent,
      borderWidth: 2,
      paddingHorizontal: spacing.md - 1
    },
    invalid: { borderColor: colors.error },
    input: {
      ...typography.body,
      flex: 1,
      color: colors.text.primary,
      paddingVertical: spacing.sm
    }
  })
)
