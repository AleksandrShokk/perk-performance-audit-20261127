import { useInfiniteQuery, useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Pressable, View } from 'react-native'

import { type ProductModel, catalogGroupSave, catalogProducts } from '@app/api'

import { Button, Notice, Text, TextField } from '@/components/ui'

import { useAuth } from '@/features/auth/providers/AuthProvider'
import { useWorkspace } from '@/features/workspace/providers/WorkspaceProvider'

import { errorMessage } from '@/lib/errors'

import { useRefreshProducts } from '../hooks/useProducts'

import { ProductPhoto } from './ProductPhoto'
import { createStyles } from '@/theme'

export function GroupingForm({
  model,
  workspaceId,
  article,
  onSaved,
  onCancel
}: {
  model: ProductModel
  workspaceId: string
  article?: string
  onSaved: () => Promise<void>
  onCancel: () => void
}) {
  const styles = useStyles()
  const { user } = useAuth()
  const { accessKey } = useWorkspace()
  const refresh = useRefreshProducts()
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const [selected, setSelected] = useState(
    model.products.map(item => item.nm_id)
  )
  const [title, setTitle] = useState(model.title)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const query = useInfiniteQuery({
    queryKey: [
      'user',
      user?.id,
      workspaceId,
      'grouping-candidates',
      model.store_id,
      accessKey,
      appliedSearch
    ],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      catalogProducts(
        workspaceId,
        {
          store_id: model.store_id,
          q: appliedSearch,
          limit: 50,
          offset: pageParam
        },
        { signal }
      ),
    getNextPageParam: page =>
      page.offset + page.items.length < page.total
        ? page.offset + page.limit
        : undefined,
    meta: { persist: false }
  })
  const candidates = [
    ...new Map(
      [
        ...model.products,
        ...(query.data?.pages.flatMap(page => page.items) ?? [])
      ].map(item => [item.nm_id, item])
    ).values()
  ]
  const save = useMutation({
    mutationFn: (articles: string[]) =>
      catalogGroupSave(workspaceId, model.store_id, {
        articles,
        title: articles.length > 1 ? title : ''
      }),
    onSuccess: async () => {
      if (mounted.current) await onSaved()
      else void refresh()
    }
  })
  function toggle(id: string) {
    setSelected(values =>
      values.includes(id)
        ? values.filter(value => value !== id)
        : [...values, id]
    )
  }
  return (
    <View style={styles.content}>
      <TextField
        label='Название карточки'
        value={title}
        onChangeText={setTitle}
        maxLength={200}
      />
      <TextField
        label='Найти товары для объединения'
        value={search}
        onChangeText={setSearch}
        maxLength={100}
        returnKeyType='search'
        onSubmitEditing={() => setAppliedSearch(search.trim())}
      />
      <Button
        title='Найти'
        variant='secondary'
        onPress={() => setAppliedSearch(search.trim())}
      />
      <Text variant='labelStrong'>Выбрано: {selected.length}</Text>
      {(save.error || query.error) && (
        <Notice
          tone='error'
          message={errorMessage(save.error ?? query.error)}
        />
      )}
      {query.isPending && <Text tone='secondary'>Загрузка товаров…</Text>}
      {candidates.map(item => (
        <Pressable
          key={item.nm_id}
          onPress={() => toggle(item.nm_id)}
          accessibilityRole='checkbox'
          accessibilityLabel={`${item.vendor_code || item.nm_id} ${item.colors.join(', ')}`}
          accessibilityState={{ checked: selected.includes(item.nm_id) }}
          style={[
            styles.item,
            selected.includes(item.nm_id) && styles.selected
          ]}
        >
          <ProductPhoto
            uri={item.photos?.[0]}
            label={item.title}
            style={styles.photo}
          />
          <View style={styles.name}>
            <Text variant='labelStrong'>{item.vendor_code || item.nm_id}</Text>
            <Text
              variant='caption'
              tone='secondary'
            >
              {item.title} · {item.colors.join(', ')}
            </Text>
          </View>
          <Text variant='bodyStrong'>
            {selected.includes(item.nm_id) ? '✓' : '○'}
          </Text>
        </Pressable>
      ))}
      {query.hasNextPage && (
        <Button
          title='Ещё товары'
          variant='ghost'
          loading={query.isFetchingNextPage}
          onPress={() => void query.fetchNextPage()}
        />
      )}
      <Button
        title='Сохранить объединение'
        disabled={selected.length < 2 || selected.length > 200}
        loading={save.isPending}
        onPress={() => save.mutate(selected)}
      />
      {model.products.length > 1 && (
        <Button
          title='Отделить выбранный вариант'
          variant='secondary'
          disabled={save.isPending}
          onPress={() => save.mutate([article ?? model.products[0]!.nm_id])}
        />
      )}
      <Button
        title='Назад к товару'
        variant='ghost'
        disabled={save.isPending}
        onPress={onCancel}
      />
    </View>
  )
}
const useStyles = createStyles(({ colors, spacing, radius, sizes }) => ({
  content: { gap: spacing.md },
  item: {
    minHeight: sizes.touchTarget,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.sm,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.border
  },
  selected: { backgroundColor: colors.accentSoft, borderColor: colors.accent },
  name: { flex: 1, gap: spacing.xxs },
  photo: { width: spacing.xxl * 2, aspectRatio: 3 / 4 }
}))
