import { Tabs } from 'expo-router'
import {
  ChartNoAxesCombined,
  LayoutGrid,
  Package,
  SlidersHorizontal
} from 'lucide-react-native'

import { useTheme } from '@/theme'

// В браузере обычная нижняя навигация; на iOS и Android остаются Native Tabs.
export default function WebTabsLayout() {
  const { colors } = useTheme()
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.text.secondary,
        tabBarStyle: {
          backgroundColor: colors.background.card,
          borderTopColor: colors.border
        }
      }}
    >
      <Tabs.Screen
        name='index'
        options={{
          title: 'Обзор',
          tabBarIcon: ({ color, size }) => (
            <LayoutGrid
              color={color}
              size={size}
            />
          )
        }}
      />
      <Tabs.Screen
        name='products'
        options={{
          title: 'Товары',
          tabBarIcon: ({ color, size }) => (
            <Package
              color={color}
              size={size}
            />
          )
        }}
      />
      <Tabs.Screen
        name='finance'
        options={{
          title: 'Финансы',
          tabBarIcon: ({ color, size }) => (
            <ChartNoAxesCombined
              color={color}
              size={size}
            />
          )
        }}
      />
      <Tabs.Screen
        name='more'
        options={{
          title: 'Ещё',
          tabBarIcon: ({ color, size }) => (
            <SlidersHorizontal
              color={color}
              size={size}
            />
          )
        }}
      />
    </Tabs>
  )
}
