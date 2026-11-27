'use client'

import { useState } from 'react'

import { Empty } from '@/components/feedback'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

import { useWorkspace } from '@/features/workspace/workspace-provider'

import { CostImport } from './cost-import'
import { ExpenseForm } from './expense-form'
import { ExpenseHistory } from './expense-history'
import { FinanceField } from './finance-field'
import { TaxForm } from './tax-form'

export type FinanceAction = 'expense' | 'cost' | 'tax' | 'history'
export type ActionSession = { kind: FinanceAction; id: string }
const titles = {
  expense: 'Добавить расход',
  cost: 'Себестоимость товаров',
  tax: 'Налоговые настройки',
  history: 'История внешних расходов'
}
const descriptions = {
  expense: 'Расходы вне отчётов маркетплейса',
  cost: 'Импорт цен из шаблона XLSX',
  tax: 'Настройки применяются с указанной даты',
  history: 'Все даты'
}

export function FinanceActionDialog({
  action,
  onClose,
  onSaved,
  onRefresh,
  date,
  currency
}: {
  action: ActionSession
  onClose: () => void
  onSaved: () => Promise<unknown>
  onRefresh: () => Promise<unknown>
  date: string
  currency: string
}) {
  const scope = useWorkspace()
  const [storeId, setStoreId] = useState(scope.store?.id ?? '')
  const stores = scope.selected.filter(store =>
    store.features.includes(action.kind === 'cost' ? 'catalog' : 'finance')
  )
  const store = stores.find(store => store.id === storeId)
  return (
    <Dialog
      open
      onOpenChange={open => {
        if (!open) onClose()
      }}
    >
      <DialogContent
        className={`finance-dialog ${action.kind === 'cost' || action.kind === 'history' ? 'wide' : ''}`}
      >
        <DialogHeader>
          <DialogTitle>{titles[action.kind]}</DialogTitle>
          <DialogDescription>{descriptions[action.kind]}</DialogDescription>
        </DialogHeader>
        <div className='finance-dialog-scroll'>
          {!stores.length ? (
            <Empty title='Нет подходящего кабинета' />
          ) : !store ? (
            <FinanceField label='Кабинет'>
              <select
                autoFocus
                className='finance-input'
                value=''
                onChange={event => setStoreId(event.target.value)}
              >
                <option
                  value=''
                  disabled
                >
                  Выберите кабинет
                </option>
                {stores.map(store => (
                  <option
                    key={store.id}
                    value={store.id}
                  >
                    {store.name} ·{' '}
                    {store.marketplace === 'ozon' ? 'Ozon' : 'WB'}
                  </option>
                ))}
              </select>
            </FinanceField>
          ) : (
            <>
              <div className='finance-dialog-store'>
                {store.name}
                <span>
                  {store.marketplace === 'ozon' ? 'Ozon' : 'Wildberries'}
                </span>
              </div>
              {action.kind === 'expense' && (
                <ExpenseForm
                  workspaceId={scope.workspace!.id}
                  storeId={store.id}
                  date={date}
                  currency={currency}
                  onSaved={onSaved}
                />
              )}
              {action.kind === 'cost' && (
                <CostImport
                  workspaceId={scope.workspace!.id}
                  storeId={store.id}
                  date={date}
                  currency={currency}
                  onSaved={onSaved}
                />
              )}
              {action.kind === 'tax' && (
                <TaxForm
                  workspaceId={scope.workspace!.id}
                  storeId={store.id}
                  date={date}
                  currency={currency}
                  onSaved={onSaved}
                />
              )}
              {action.kind === 'history' && (
                <ExpenseHistory
                  workspaceId={scope.workspace!.id}
                  storeId={store.id}
                  date={date}
                  currency={currency}
                  onSaved={onRefresh}
                />
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
