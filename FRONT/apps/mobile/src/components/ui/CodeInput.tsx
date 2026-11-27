import { Platform, StyleSheet, TextInput, View } from 'react-native'

import { Text } from './Text'
import { createStyles } from '@/theme'

const LENGTH = 6

export type CodeInputProps = {
  value: string
  onChangeText: (code: string) => void
  /** Вызывается, когда введены все 6 цифр. */
  onComplete?: (code: string) => void
  error?: string
  editable?: boolean
  autoFocus?: boolean
}

/** Одно нативное поле поверх шести ячеек; поддерживает вставку и автоподстановку кода. */
export function CodeInput({
  value,
  onChangeText,
  onComplete,
  error,
  editable = true,
  autoFocus = true
}: CodeInputProps) {
  const styles = useStyles()
  const active = Math.min(value.length, LENGTH - 1)

  function change(text: string) {
    const digits = text.replace(/\D/g, '').slice(0, LENGTH)
    onChangeText(digits)
    if (digits.length === LENGTH) onComplete?.(digits)
  }

  return (
    <View style={styles.wrapper}>
      <View style={styles.control}>
        <View
          pointerEvents='none'
          accessibilityElementsHidden
          importantForAccessibility='no-hide-descendants'
          style={styles.cells}
        >
          {Array.from({ length: LENGTH }, (_, index) => (
            <View
              key={index}
              style={[
                styles.cell,
                editable && index === active && styles.activeCell,
                !!error && styles.invalidCell
              ]}
            >
              <Text
                variant='value'
                tabular
              >
                {value[index] ?? ''}
              </Text>
            </View>
          ))}
        </View>
        {/* Нажатие получает само поле, в том числе после закрытия клавиатуры Android. */}
        <TextInput
          value={value}
          onChangeText={change}
          editable={editable}
          autoFocus={autoFocus}
          keyboardType='number-pad'
          textContentType='oneTimeCode'
          autoComplete='one-time-code'
          maxLength={LENGTH}
          caretHidden
          selection={{ start: value.length, end: value.length }}
          underlineColorAndroid='transparent'
          accessibilityLabel='Код подтверждения'
          style={styles.input}
        />
      </View>
      {error && (
        <Text
          variant='caption'
          tone='error'
          align='center'
        >
          {error}
        </Text>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, radius, spacing }) => ({
  wrapper: { gap: spacing.sm },
  control: { position: 'relative' },
  cells: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.xs
  },
  cell: {
    flex: 1,
    aspectRatio: 0.85,
    maxHeight: 64,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background.card
  },
  activeCell: { borderColor: colors.accent, borderWidth: 2 },
  invalidCell: { borderColor: colors.error },
  input: {
    ...StyleSheet.absoluteFill,
    // На Android скрываем и нативную отрисовку цифр, сохраняя область нажатия.
    opacity: Platform.OS === 'android' ? 0 : 1,
    color: 'transparent',
    backgroundColor: 'transparent',
    outlineWidth: 0,
    padding: 0
  }
}))
