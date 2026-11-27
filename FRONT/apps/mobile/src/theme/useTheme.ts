import { useColorScheme } from 'react-native'

import { type Theme, themes } from './theme'

export function useTheme(): Theme {
  return themes[useColorScheme() === 'dark' ? 'dark' : 'light']
}
