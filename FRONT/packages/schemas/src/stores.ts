import {
  StoreConnectOzonBody,
  StoreConnectWildberriesBody,
  StoreReplaceCredentialBody,
  StoreReplaceOzonCredentialBody
} from '@app/api/zod'
import { z } from 'zod'

export const connectStoreSchema = StoreConnectWildberriesBody.extend({
  name: StoreConnectWildberriesBody.shape.name
    .trim()
    .min(1, 'Введите название магазина'),
  token: StoreConnectWildberriesBody.shape.token.trim()
})

export type ConnectStoreValues = z.infer<typeof connectStoreSchema>

export const replaceStoreTokenSchema = z.object({
  token: z
    .string()
    .trim()
    .min(1, 'Вставьте токен Wildberries')
    .pipe(StoreReplaceCredentialBody.shape.token)
})

export type ReplaceStoreTokenValues = z.infer<typeof replaceStoreTokenSchema>

export const connectOzonSchema = StoreConnectOzonBody.extend({
  name: StoreConnectOzonBody.shape.name
    .trim()
    .min(1, 'Введите название магазина'),
  client_id: z.string().trim().pipe(StoreConnectOzonBody.shape.client_id),
  api_key: z.string().trim().pipe(StoreConnectOzonBody.shape.api_key)
})
export type ConnectOzonValues = z.infer<typeof connectOzonSchema>

export const replaceOzonKeySchema = StoreReplaceOzonCredentialBody.pick({
  api_key: true
}).extend({
  api_key: z.string().trim().pipe(StoreReplaceOzonCredentialBody.shape.api_key)
})
export type ReplaceOzonKeyValues = z.infer<typeof replaceOzonKeySchema>
