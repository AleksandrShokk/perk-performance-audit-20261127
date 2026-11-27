import { File, Paths } from 'expo-file-system'
import * as Sharing from 'expo-sharing'

export async function saveTemplate(bytes: ArrayBuffer, mimeType: string) {
  if (!(await Sharing.isAvailableAsync()))
    throw new Error('Сохранение файла недоступно на устройстве')
  const file = new File(Paths.cache, 'perk-cost-template.xlsx')
  await file.create({ overwrite: true })
  await file.write(new Uint8Array(bytes))
  await Sharing.shareAsync(file.uri, {
    mimeType,
    dialogTitle: 'Сохранить шаблон себестоимости'
  })
}
