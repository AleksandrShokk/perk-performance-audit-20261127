import { Check, X } from 'lucide-react-native'
import { useState } from 'react'
import { Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Button, Text } from '@/components/ui'

import { DateRangeEditor } from '@/features/periods/components/DateRangeEditor'
import { rangeError } from '@/features/periods/model/periodRange'

import { homePeriod } from '../model/overviewMetrics'
import { HOME_PERIODS, type HomeFilters } from '../model/overviewTypes'

import { createStyles, useTheme } from '@/theme'

export function SalesFiltersSheet({
  value,
  onApply,
  onClose
}: {
  value: HomeFilters
  onApply: (value: HomeFilters) => void
  onClose: () => void
}) {
  const styles = useStyles()
  const { colors, spacing } = useTheme()
  const insets = useSafeAreaInsets()
  const [draft, setDraft] = useState(value)
  const custom = typeof draft.period === 'object'
  const error = custom ? rangeError(homePeriod(draft.period), 28) : undefined
  return (
    <Modal
      transparent
      animationType='slide'
      onRequestClose={onClose}
    >
      <View style={styles.overlay}>
        <Pressable
          accessibilityRole='button'
          accessibilityLabel='Закрыть фильтры'
          onPress={onClose}
          style={styles.backdrop}
        />
        <View
          accessibilityViewIsModal
          style={[
            styles.sheet,
            { paddingBottom: Math.max(insets.bottom, spacing.lg) }
          ]}
        >
          <View style={styles.handle} />
          <View style={styles.heading}>
            <Text variant='sectionTitle'>Фильтры графика</Text>
            <Pressable
              accessibilityRole='button'
              accessibilityLabel='Закрыть'
              onPress={onClose}
              style={styles.close}
            >
              <X
                size={20}
                color={colors.text.secondary}
              />
            </Pressable>
          </View>
          <ScrollView
            bounces={false}
            contentContainerStyle={styles.options}
          >
            <ChoiceGroup
              title='Период'
              options={
                [
                  ...HOME_PERIODS,
                  { value: 'custom', label: 'Свои даты' }
                ] as const
              }
              value={typeof draft.period === 'object' ? 'custom' : draft.period}
              onChange={period =>
                setDraft({
                  ...draft,
                  period:
                    period === 'custom' ? homePeriod(draft.period) : period
                })
              }
            />
            {custom && (
              <DateRangeEditor
                value={homePeriod(draft.period)}
                maxDays={28}
                onChange={period => setDraft({ ...draft, period })}
              />
            )}
            <ChoiceGroup
              title='Сравнение заказов'
              options={
                [
                  { value: 'buyouts', label: 'С выкупленными' },
                  { value: 'previous', label: 'С прошлым периодом' }
                ] as const
              }
              value={draft.comparison}
              onChange={comparison => setDraft({ ...draft, comparison })}
            />
            <ChoiceGroup
              title='Единица измерения'
              options={
                [
                  { value: 'amount', label: 'Сумма' },
                  { value: 'units', label: 'Штуки' }
                ] as const
              }
              value={draft.unit}
              onChange={unit => setDraft({ ...draft, unit })}
            />
          </ScrollView>
          <Button
            title='Применить'
            disabled={!!error}
            onPress={() => {
              if (!error) onApply(draft)
            }}
          />
        </View>
      </View>
    </Modal>
  )
}

function ChoiceGroup<Value extends string | number>({
  title,
  options,
  value,
  onChange
}: {
  title: string
  options: readonly { value: Value; label: string }[]
  value: Value
  onChange: (value: Value) => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <View style={styles.group}>
      <Text
        variant='caption'
        tone='secondary'
      >
        {title.toUpperCase()}
      </Text>
      <View style={styles.choices}>
        {options.map(option => {
          const selected = value === option.value
          return (
            <Pressable
              key={option.value}
              accessibilityRole='radio'
              accessibilityState={{ checked: selected }}
              onPress={() => onChange(option.value)}
              style={[styles.choice, selected && styles.selected]}
            >
              {selected && (
                <Check
                  size={14}
                  color={colors.accent}
                />
              )}
              <Text
                variant='labelStrong'
                tone={selected ? 'accent' : 'primary'}
              >
                {option.label}
              </Text>
            </Pressable>
          )
        })}
      </View>
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: colors.shadow
  },
  sheet: {
    maxHeight: '85%',
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    backgroundColor: colors.background.card,
    paddingHorizontal: spacing.lg
  },
  handle: {
    width: spacing.huge,
    height: spacing.xxs,
    alignSelf: 'center',
    backgroundColor: colors.border,
    borderRadius: radius.pill,
    marginTop: spacing.sm
  },
  heading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginVertical: spacing.sm
  },
  close: {
    width: sizes.touchTarget,
    height: sizes.touchTarget,
    alignItems: 'center',
    justifyContent: 'center'
  },
  options: { gap: spacing.xl, paddingBottom: spacing.xl },
  group: { gap: spacing.sm },
  choices: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  choice: {
    minHeight: sizes.touchTarget,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.control,
    backgroundColor: colors.background.screen,
    borderWidth: 1,
    borderColor: 'transparent',
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xxs
  },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accent }
}))
