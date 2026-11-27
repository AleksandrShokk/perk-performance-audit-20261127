import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { costsApplyImport } from '@app/api'

import { Button, Notice, Text } from '@/components/ui'

import { errorMessage } from '@/lib/errors'

import {
  chooseCostFile,
  downloadCostTemplate,
  financeStorePath
} from '../api/financeApi'
import { useRefreshFinance } from '../hooks/useFinance'

export function CostImport({
  workspaceId,
  storeId,
  onSaved
}: {
  workspaceId: string
  storeId: string
  onSaved: () => Promise<unknown>
}) {
  const mounted = useRef(true)
  const refresh = useRefreshFinance()
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const path = financeStorePath(workspaceId, storeId)
  const template = useMutation({ mutationFn: () => downloadCostTemplate(path) })
  const preview = useMutation({ mutationFn: () => chooseCostFile(path) })
  const apply = useMutation({
    mutationFn: () =>
      costsApplyImport(workspaceId, storeId, preview.data!.preview_id!),
    onSuccess: async () => {
      if (mounted.current) await onSaved()
      else void refresh()
    }
  })
  const error = template.error ?? preview.error ?? apply.error
  return (
    <>
      <Text
        variant='label'
        tone='secondary'
      >
        Заполните цены и даты в шаблоне XLSX.
      </Text>
      {error && (
        <Notice
          tone='error'
          message={errorMessage(error)}
        />
      )}
      <Button
        title='Скачать шаблон XLSX'
        variant='secondary'
        loading={template.isPending}
        onPress={() => template.mutate()}
      />
      <Button
        title='Выбрать заполненный файл'
        variant='secondary'
        loading={preview.isPending}
        onPress={() => preview.mutate()}
      />
      {preview.data && (
        <>
          <Text variant='bodyStrong'>
            Готово строк: {preview.data.valid_count} из{' '}
            {preview.data.rows_count}
          </Text>
          {preview.data.errors.slice(0, 8).map((error, index) => (
            <Text
              key={`${error.row}:${index}`}
              variant='caption'
              tone='error'
            >
              Строка {error.row}: {error.message}
            </Text>
          ))}

          <Button
            title='Применить себестоимость'
            loading={apply.isPending}
            disabled={!preview.data.can_apply || !preview.data.preview_id}
            onPress={() => apply.mutate()}
          />
        </>
      )}
    </>
  )
}
