import { describe, expect, it } from 'vitest'

import { supplyTemplateMappingSchema } from '@app/schemas'

import type { TemplateInspection } from '@app/api'

import { initialTemplateMapping, validateTemplateFile } from './template'

const metadata = {
  suggested: null,
  sheets: [
    {
      name: 'Поставка',
      headers: [
        {
          row: 3,
          columns: [
            { key: 'D', label: 'Баркод' },
            { key: 'G', label: 'Количество' }
          ]
        }
      ]
    }
  ],
  choices: [{ value: 'barcode', error: null }]
} as TemplateInspection
describe('original supply templates', () => {
  it('uses an explicit backend suggestion or starts with real columns', () => {
    const mapping = initialTemplateMapping(metadata)
    expect(mapping).toMatchObject({
      sheet: 'Поставка',
      header_row: 3,
      first_row: 4,
      identifier_column: 'D',
      quantity_column: 'G'
    })
    expect(
      initialTemplateMapping({
        ...metadata,
        suggested: { ...mapping, mode: 'match' }
      }).mode
    ).toBe('match')
  })
  it('rejects overlapping columns and rows before goods without guessing a layout', () => {
    const mapping = initialTemplateMapping(metadata)
    expect(supplyTemplateMappingSchema.safeParse(mapping).success).toBe(true)
    expect(
      supplyTemplateMappingSchema.safeParse({
        ...mapping,
        quantity_column: 'D'
      }).success
    ).toBe(false)
    expect(
      supplyTemplateMappingSchema.safeParse({ ...mapping, first_row: 3 })
        .success
    ).toBe(false)
  })
  it('rejects unsupported and oversized browser files before uploading', () => {
    expect(() =>
      validateTemplateFile(new File(['data'], 'template.xls'))
    ).toThrow('XLSX')
    expect(() =>
      validateTemplateFile(
        new File([new Uint8Array(256 * 1024 + 1)], 'template.xlsx')
      )
    ).toThrow('256')
    expect(() =>
      validateTemplateFile(new File(['data'], 'template.XLSX'))
    ).not.toThrow()
  })
})
