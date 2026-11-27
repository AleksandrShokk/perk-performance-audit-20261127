import { View } from 'react-native'

import { createStyles } from '@/theme'

export function Divider() {
  return <View style={useStyles().line} />
}

const useStyles = createStyles(({ colors, sizes }) => ({
  line: { height: sizes.hairline, backgroundColor: colors.border }
}))
