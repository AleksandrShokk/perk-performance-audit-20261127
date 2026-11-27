import { CalendarDays, X } from 'lucide-react-native'
import { useState } from 'react'
import { Modal, Pressable, ScrollView, StyleSheet, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Button, SegmentedControl, Text } from '@/components/ui'

import { formatDateRange } from '@/lib/format'

import {
  type ReportPeriod,
  rangeError,
  resolvePeriod
} from '../model/periodRange'

import { DateRangeEditor } from './DateRangeEditor'
import { createStyles, useTheme } from '@/theme'

export function PeriodSelect({
  value,
  onChange,
  options
}: {
  value: ReportPeriod
  onChange: (period: ReportPeriod) => void
  options: readonly { value: number; label: string }[]
}) {
  const styles = useStyles()
  const { colors, spacing } = useTheme()
  const insets = useSafeAreaInsets()
  const [draft, setDraft] = useState(() => resolvePeriod(value))
  const [open, setOpen] = useState(false)
  const custom = typeof value !== 'number'

  return (
    <View style={styles.control}>
      <SegmentedControl<number>
        options={options}
        value={custom ? -1 : value}
        onChange={onChange}
      />
      <Pressable
        accessibilityRole='button'
        accessibilityLabel='Выбрать свой период'
        accessibilityState={{ selected: custom }}
        onPress={() => {
          setDraft(resolvePeriod(value))
          setOpen(true)
        }}
        style={[styles.custom, custom && styles.active]}
      >
        <CalendarDays
          size={18}
          color={custom ? colors.accent : colors.text.secondary}
        />
        <Text
          variant='labelStrong'
          tone={custom ? 'accent' : 'secondary'}
        >
          {custom
            ? formatDateRange(value.date_from, value.date_to)
            : 'Свои даты'}
        </Text>
      </Pressable>
      {open && (
        <Modal
          transparent
          animationType='slide'
          onRequestClose={() => setOpen(false)}
        >
          <View style={styles.overlay}>
            <Pressable
              accessibilityRole='button'
              accessibilityLabel='Закрыть календарь'
              onPress={() => setOpen(false)}
              style={styles.backdrop}
            />
            <View
              accessibilityViewIsModal
              style={[
                styles.sheet,
                { paddingBottom: Math.max(insets.bottom, spacing.lg) }
              ]}
            >
              <View style={styles.heading}>
                <Text variant='sectionTitle'>Свой период</Text>
                <Pressable
                  accessibilityRole='button'
                  accessibilityLabel='Закрыть'
                  onPress={() => setOpen(false)}
                  style={styles.close}
                >
                  <X
                    size={20}
                    color={colors.text.secondary}
                  />
                </Pressable>
              </View>
              <ScrollView contentContainerStyle={styles.content}>
                <DateRangeEditor
                  value={draft}
                  onChange={setDraft}
                />
              </ScrollView>
              <Button
                title='Применить'
                disabled={!!rangeError(draft)}
                onPress={() => {
                  if (!rangeError(draft)) {
                    onChange(draft)
                    setOpen(false)
                  }
                }}
              />
            </View>
          </View>
        </Modal>
      )}
    </View>
  )
}

const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  control: { gap: spacing.xs },
  custom: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: 'transparent'
  },
  active: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  overlay: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFill, backgroundColor: colors.shadow },
  sheet: {
    maxHeight: '90%',
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    backgroundColor: colors.background.card,
    paddingHorizontal: spacing.lg
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
  content: { paddingBottom: spacing.lg }
}))
