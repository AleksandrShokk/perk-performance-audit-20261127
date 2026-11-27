import { useState } from 'react'
import { View } from 'react-native'

import { Button, Notice, Text } from '@/components/ui'

import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { useRefreshFinance } from '../hooks/useFinance'

import { CostImport } from './CostImport'
import { ExpenseForm } from './ExpenseForm'
import { FinanceSheet } from './FinanceSheet'
import { TaxForm } from './TaxForm'
import { createStyles } from '@/theme'

type Action = 'expense' | 'cost' | 'tax'
const titles = {
  expense: 'Добавить расход',
  cost: 'Себестоимость товаров',
  tax: 'Налоговые настройки'
}

export function FinanceActions({
  date,
  endDate,
  currency
}: {
  date: string
  endDate: string
  currency: string
}) {
  const { store, workspace, can } = useWorkspace()
  if (
    !['costs.write', 'expenses.write', 'taxes.write'].some(permission =>
      can(permission as 'costs.write' | 'expenses.write' | 'taxes.write')
    )
  )
    return null
  if (!store || !workspace)
    return (
      <Text
        variant='caption'
        tone='secondary'
      >
        Выберите магазин для настройки.
      </Text>
    )
  return (
    <StoreActions
      key={`${workspace.id}:${store.id}`}
      workspaceId={workspace.id}
      storeId={store.id}
      date={date}
      endDate={endDate}
      currency={currency}
    />
  )
}

function StoreActions({
  workspaceId,
  storeId,
  date,
  endDate,
  currency
}: {
  workspaceId: string
  storeId: string
  date: string
  endDate: string
  currency: string
}) {
  const styles = useStyles()
  const refresh = useRefreshFinance()
  const { can } = useWorkspace()
  const [action, setAction] = useState<Action | null>(null)
  const [saved, setSaved] = useState(false)
  const onSaved = async () => {
    await refresh()
    setAction(null)
    setSaved(true)
  }
  return (
    <>
      <View style={styles.actions}>
        {can('expenses.write') && (
          <Button
            title='Добавить расход'
            variant='secondary'
            onPress={() => {
              setSaved(false)
              setAction('expense')
            }}
          />
        )}
        {can('costs.write') && (
          <Button
            title='Себестоимость'
            variant='secondary'
            onPress={() => {
              setSaved(false)
              setAction('cost')
            }}
          />
        )}
        {can('taxes.write') && (
          <Button
            title='Налоги'
            variant='ghost'
            onPress={() => {
              setSaved(false)
              setAction('tax')
            }}
          />
        )}
      </View>
      {saved && (
        <Notice
          tone='success'
          message='Сохранено. Финансовые данные обновлены.'
        />
      )}
      {action && (
        <FinanceSheet
          title={titles[action]}
          onClose={() => setAction(null)}
        >
          {action === 'expense' && can('expenses.write') && (
            <ExpenseForm
              {...{ workspaceId, storeId, date: endDate, currency, onSaved }}
            />
          )}
          {action === 'cost' && can('costs.write') && (
            <CostImport {...{ workspaceId, storeId, onSaved }} />
          )}
          {action === 'tax' && can('taxes.write') && (
            <TaxForm {...{ workspaceId, storeId, date, onSaved }} />
          )}
        </FinanceSheet>
      )}
    </>
  )
}

const useStyles = createStyles(({ spacing }) => ({
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }
}))
