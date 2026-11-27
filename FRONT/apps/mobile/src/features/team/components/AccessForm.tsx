import { Check } from 'lucide-react-native'
import { Pressable, View } from 'react-native'

import type { RoleInput, StoreResponse } from '@app/api'

import { Text } from '@/components/ui'

import {
  PERMISSION_OPTIONS,
  ROLE_DEFAULTS,
  ROLE_LABELS,
  ROLE_OPTIONS,
  isAdminRole,
  togglePermission
} from '../model/permissions'

import { createStyles, useTheme } from '@/theme'

export function AccessForm({
  value,
  onChange,
  stores
}: {
  value: RoleInput
  onChange: (value: RoleInput) => void
  stores: StoreResponse[]
}) {
  const styles = useStyles()
  const full = isAdminRole(value.role)
  const permissions =
    value.permissions ?? ROLE_DEFAULTS[value.role ?? 'viewer'] ?? []
  return (
    <View style={styles.fields}>
      <Text variant='bodyStrong'>Роль</Text>
      <View style={styles.roles}>
        {ROLE_OPTIONS.map(role => (
          <Choice
            key={role}
            label={ROLE_LABELS[role]!}
            selected={value.role === role}
            onPress={() =>
              onChange({
                role,
                permissions: ROLE_DEFAULTS[role],
                store_ids: role === 'admin' ? null : value.store_ids
              })
            }
          />
        ))}
      </View>
      {full ? (
        <Text tone='secondary'>Все функции и магазины</Text>
      ) : (
        <>
          <Text variant='bodyStrong'>Магазины</Text>
          <Choice
            label='Все магазины, включая новые'
            selected={value.store_ids == null}
            onPress={() =>
              onChange({
                ...value,
                store_ids: value.store_ids == null ? [] : null
              })
            }
          />
          {stores.map(store => (
            <Choice
              key={store.id}
              label={store.name}
              selected={
                value.store_ids == null || value.store_ids.includes(store.id)
              }
              onPress={() => {
                const selected = value.store_ids ?? stores.map(item => item.id)
                onChange({
                  ...value,
                  store_ids: selected.includes(store.id)
                    ? selected.filter(id => id !== store.id)
                    : [...selected, store.id]
                })
              }}
            />
          ))}
          <Text variant='bodyStrong'>Права</Text>
          {PERMISSION_OPTIONS.map(([permission, label]) => (
            <Choice
              key={permission}
              label={label}
              selected={permissions.includes(permission)}
              onPress={() =>
                onChange({
                  ...value,
                  permissions: togglePermission(permissions, permission)
                })
              }
            />
          ))}
        </>
      )}
    </View>
  )
}

function Choice({
  label,
  selected,
  onPress
}: {
  label: string
  selected: boolean
  onPress: () => void
}) {
  const styles = useStyles()
  const { colors } = useTheme()
  return (
    <Pressable
      accessibilityRole='checkbox'
      accessibilityState={{ checked: selected }}
      onPress={onPress}
      style={styles.choice}
    >
      <View style={[styles.check, selected && styles.selected]}>
        {selected && (
          <Check
            size={16}
            color={colors.accent}
          />
        )}
      </View>
      <Text
        variant='label'
        style={styles.label}
      >
        {label}
      </Text>
    </Pressable>
  )
}
const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  fields: { gap: spacing.sm },
  roles: { gap: spacing.xs },
  choice: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm
  },
  label: { flex: 1 },
  check: {
    width: 24,
    height: 24,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.chip,
    justifyContent: 'center',
    alignItems: 'center'
  },
  selected: { borderColor: colors.accent, backgroundColor: colors.accentSoft }
}))
