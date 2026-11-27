import * as DocumentPicker from 'expo-document-picker'
import { Platform } from 'react-native'

import { type ImportPreview, http } from '@app/api'

import { saveTemplate } from './fileDownload'

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export const financeStorePath = (workspaceId: string, storeId: string) =>
  `/api/v1/workspaces/${workspaceId}/stores/${storeId}`

export async function chooseCostFile(path: string) {
  const selected = await DocumentPicker.getDocumentAsync({
    type: XLSX,
    multiple: false,
    copyToCacheDirectory: true
  })
  if (selected.canceled) return undefined
  const asset = selected.assets[0]!
  const form = new FormData()
  // Web передаёт File, нативная FormData — ссылку на выбранный локальный файл.
  const file =
    Platform.OS === 'web'
      ? asset.file!
      : {
          uri: asset.uri,
          name: asset.name,
          type: asset.mimeType ?? XLSX
        }
  form.append('file', file as Blob)
  const response = await http.post<ImportPreview>(
    `${path}/cost-imports`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' }
    }
  )
  return response.data
}

export async function downloadCostTemplate(path: string) {
  const { data } = await http.get<ArrayBuffer>(`${path}/costs/template`, {
    responseType: 'arraybuffer'
  })
  await saveTemplate(data, XLSX)
}
