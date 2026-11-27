import {
  PERMISSION_OPTIONS,
  ROLE_DEFAULTS,
  ROLE_LABELS,
  ROLE_OPTIONS,
  togglePermission
} from '@app/analytics/permissions'

import type { RoleInput, StoreResponse } from '@app/api'

export function AccessForm({
  value,
  onChange,
  stores
}: {
  value: RoleInput
  onChange: (value: RoleInput) => void
  stores: StoreResponse[]
}) {
  const permissions =
    value.permissions ?? ROLE_DEFAULTS[value.role ?? 'manager'] ?? []
  return (
    <div className='access-form'>
      <label className='field'>
        <span>Роль</span>
        <select
          className='native-select'
          aria-label='Роль сотрудника'
          value={value.role ?? 'manager'}
          onChange={event => {
            const role = event.target.value as RoleInput['role']
            onChange({
              role,
              permissions: ROLE_DEFAULTS[role!],
              store_ids: role === 'admin' ? null : value.store_ids
            })
          }}
        >
          {ROLE_OPTIONS.map(role => (
            <option
              key={role}
              value={role}
            >
              {ROLE_LABELS[role]}
            </option>
          ))}
        </select>
      </label>
      {value.role === 'admin' ? (
        <p className='muted'>Все функции и кабинеты</p>
      ) : (
        <>
          <fieldset className='access-choices'>
            <legend>Кабинеты</legend>
            <label>
              <input
                type='checkbox'
                checked={value.store_ids == null}
                onChange={() =>
                  onChange({
                    ...value,
                    store_ids: value.store_ids == null ? [] : null
                  })
                }
              />
              Все кабинеты, включая новые
            </label>
            {stores.map(store => (
              <label key={store.id}>
                <input
                  type='checkbox'
                  checked={
                    value.store_ids == null ||
                    value.store_ids.includes(store.id)
                  }
                  onChange={() => {
                    const selected =
                      value.store_ids ?? stores.map(item => item.id)
                    onChange({
                      ...value,
                      store_ids: selected.includes(store.id)
                        ? selected.filter(id => id !== store.id)
                        : [...selected, store.id]
                    })
                  }}
                />
                {store.name}
              </label>
            ))}
          </fieldset>
          <fieldset className='access-choices'>
            <legend>Права</legend>
            {PERMISSION_OPTIONS.map(([key, label]) => (
              <label key={key}>
                <input
                  type='checkbox'
                  checked={permissions.includes(key)}
                  onChange={() =>
                    onChange({
                      ...value,
                      permissions: togglePermission(permissions, key)
                    })
                  }
                />
                {label}
              </label>
            ))}
          </fieldset>
        </>
      )}
    </div>
  )
}
