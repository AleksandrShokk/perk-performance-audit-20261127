import type { TemplateInspection, TemplateMapping } from '@app/api'

export const emptyTemplateMapping: TemplateMapping = {
  sheet: '',
  header_row: 1,
  first_row: 2,
  identifier_column: 'A',
  quantity_column: 'B',
  identifier_type: 'barcode',
  mode: 'append'
}
export function initialTemplateMapping(
  data: TemplateInspection
): TemplateMapping {
  if (data.suggested) return data.suggested
  const sheet = data.sheets.find(sheet => sheet.headers.length)
  const row = sheet?.headers[0]
  return {
    ...emptyTemplateMapping,
    sheet: sheet?.name ?? '',
    header_row: row?.row ?? 1,
    first_row: (row?.row ?? 1) + 1,
    identifier_column: row?.columns[0]?.key ?? 'A',
    quantity_column: row?.columns[1]?.key ?? 'B',
    identifier_type:
      data.choices.find(choice => !choice.error)?.value ?? 'barcode'
  }
}
export function validateTemplateFile(file: File) {
  if (!file.name.toLowerCase().endsWith('.xlsx'))
    throw new Error('Выберите файл XLSX')
  if (file.size > 256 * 1024) throw new Error('Размер шаблона — до 256 КБ')
}
