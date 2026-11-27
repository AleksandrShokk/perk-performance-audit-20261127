import { NativeTabs } from 'expo-router/native-tabs'

import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useTheme } from '@/theme'

export default function TabsLayout() {
  const { colors } = useTheme()
  const { can } = useWorkspace()
  return (
    <NativeTabs
      backgroundColor={colors.background.card}
      tintColor={colors.accent}
      iconColor={{ default: colors.text.secondary, selected: colors.accent }}
      labelStyle={{
        default: { color: colors.text.secondary },
        selected: { color: colors.accent }
      }}
      indicatorColor={colors.accentSoft}
      rippleColor='transparent'
      disableIndicator
      disableTransparentOnScrollEdge
    >
      <NativeTabs.Trigger name='index'>
        <NativeTabs.Trigger.Icon
          sf={{ default: 'square.grid.2x2', selected: 'square.grid.2x2.fill' }}
          md='dashboard'
        />
        <NativeTabs.Trigger.Label>Обзор</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger
        name='products'
        hidden={!can('inventory.read')}
      >
        <NativeTabs.Trigger.Icon
          sf={{ default: 'shippingbox', selected: 'shippingbox.fill' }}
          md='inventory_2'
        />
        <NativeTabs.Trigger.Label>Товары</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger
        name='finance'
        hidden={!can('finance.read')}
      >
        <NativeTabs.Trigger.Icon
          sf={{ default: 'chart.bar', selected: 'chart.bar.fill' }}
          md='bar_chart'
        />
        <NativeTabs.Trigger.Label>Финансы</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
      <NativeTabs.Trigger name='more'>
        <NativeTabs.Trigger.Icon
          sf='slider.horizontal.3'
          md='tune'
        />
        <NativeTabs.Trigger.Label>Ещё</NativeTabs.Trigger.Label>
      </NativeTabs.Trigger>
    </NativeTabs>
  )
}
