import { type ReactNode, useState } from 'react'
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  type StyleProp,
  View,
  type ViewStyle
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { Logo } from './Logo'
import { createStyles, useTheme } from '@/theme'

export type ScreenProps = {
  children: ReactNode
  /** Логотип сверху слева. Отключать на экранах с системной кнопкой «Назад». */
  logo?: boolean
  /** Элемент справа от логотипа, например аватар профиля. */
  headerRight?: ReactNode
  /** Элемент по центру шапки, например выбор магазина. */
  headerCenter?: ReactNode
  /** Закрепить шапку при прокрутке, например на главной. */
  stickyHeader?: boolean
  /** Содержимое под прокруткой (по умолчанию да). */
  scroll?: boolean
  /** Поднимать содержимое над клавиатурой — для форм. */
  keyboard?: boolean
  /** Учитывать нижнюю системную область — для экранов без вкладок. */
  bottomInset?: boolean
  /** Extra scrollable/list spacing below content; defaults to the theme gap. */
  bottomSpacing?: number
  /** Ручное обновление. Верните Promise, чтобы индикатор дождался завершения. */
  onRefresh?: () => Promise<unknown>
  contentStyle?: StyleProp<ViewStyle>
}

export function Screen({
  children,
  logo = true,
  headerRight,
  headerCenter,
  stickyHeader = false,
  scroll = true,
  keyboard = false,
  bottomInset = false,
  bottomSpacing,
  onRefresh,
  contentStyle
}: ScreenProps) {
  const styles = useStyles()
  const { colors, spacing } = useTheme()
  const insets = useSafeAreaInsets()
  const [refreshing, setRefreshing] = useState(false)

  // Фоновый опрос не включает нативный индикатор и не меняет отступ прокрутки.
  const refresh = async () => {
    if (!onRefresh || refreshing) return
    setRefreshing(true)
    try {
      await onRefresh()
    } catch {
      // Ошибку запроса показывает сам экран через состояние данных.
    } finally {
      setRefreshing(false)
    }
  }

  // Native Tabs на iOS сами добавляют safe area в ScrollView (включая панель вкладок).
  // На Android вкладки учитывают только нижний отступ — верхний задаём сами.
  const automaticInsets = Platform.OS === 'ios' && !bottomInset && scroll
  const padding = {
    paddingTop: (automaticInsets ? 0 : insets.top) + spacing.xs,
    paddingBottom:
      (bottomInset ? insets.bottom : 0) + (bottomSpacing ?? spacing.xxl)
  }

  // StickyHeader переносит стиль прямого ребёнка на свою обёртку.
  // Горизонтальную раскладку держим во вложенном View.
  const header =
    logo || headerCenter || headerRight ? (
      <View style={styles.header}>
        <View style={styles.headerRow}>
          {headerCenter ? (
            <>
              <View style={styles.headerSide}>
                {logo && <Logo height={24} />}
              </View>
              <View style={styles.headerCenter}>{headerCenter}</View>
              <View style={[styles.headerSide, styles.headerRight]}>
                {headerRight}
              </View>
            </>
          ) : (
            <>
              {logo ? <Logo /> : <View />}
              {headerRight}
            </>
          )}
        </View>
      </View>
    ) : null
  const body = <View style={[styles.fill, contentStyle]}>{children}</View>

  const content = scroll ? (
    <ScrollView
      style={styles.fill}
      contentContainerStyle={[styles.content, padding]}
      keyboardShouldPersistTaps='handled'
      contentInsetAdjustmentBehavior={automaticInsets ? 'automatic' : 'never'}
      showsVerticalScrollIndicator={false}
      stickyHeaderIndices={stickyHeader && header ? [0] : undefined}
      refreshControl={
        onRefresh && (
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            tintColor={colors.accent}
            colors={[colors.accent]}
            progressViewOffset={insets.top}
          />
        )
      }
    >
      {header}
      {body}
    </ScrollView>
  ) : (
    <View style={[styles.fixedContent, styles.content, padding]}>
      {header}
      {body}
    </View>
  )

  return (
    <View style={styles.screen}>
      {keyboard ? (
        <KeyboardAvoidingView
          style={styles.fill}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          {content}
        </KeyboardAvoidingView>
      ) : (
        content
      )}
      {/* Прокручиваемое содержимое не должно проступать под часами и батареей. */}
      <View
        pointerEvents='none'
        style={[styles.statusBar, { height: insets.top }]}
      />
    </View>
  )
}

const useStyles = createStyles(({ colors, gaps, sizes, spacing }) => ({
  screen: { flex: 1, backgroundColor: colors.background.screen },
  statusBar: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    backgroundColor: colors.background.screen
  },
  fill: { flexGrow: 1 },
  fixedContent: { flex: 1, minHeight: 0 },
  content: { flexGrow: 1, paddingHorizontal: gaps.screenPadding },
  // Равные боковые области удерживают магазин ровно по центру экрана.
  headerSide: { width: spacing.xxl * 3 },
  headerRight: { alignItems: 'flex-end' },
  headerCenter: { flex: 1, minWidth: 0, marginHorizontal: spacing.xs },
  header: {
    backgroundColor: colors.background.screen,
    marginBottom: spacing.lg
  },
  headerRow: {
    minHeight: sizes.touchTarget,
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between'
  }
}))
