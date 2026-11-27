import { describe, expect, it } from 'vitest'

import { supplyPackagingSchema, supplyParametersSchema } from '@app/schemas'

import { defaultSupplyParameters, readSupplyParameters } from './parameters'

describe('supply planning parameters', () => {
  it('restores only valid non-sensitive interface preferences', () => {
    expect(readSupplyParameters(null)).toEqual(defaultSupplyParameters)
    expect(
      readSupplyParameters('{"target_days":60,"lead_time_days":0}')
    ).toEqual({ target_days: 60, lead_time_days: 0, include_fbs: false })
    for (const value of [
      'bad',
      '[]',
      '{"target_days":0}',
      '{"target_days":2.5}',
      '{"lead_time_days":91}'
    ])
      expect(readSupplyParameters(value)).toEqual(defaultSupplyParameters)
  })
  it('rejects partial days and boxes rather than rounding the user input', () => {
    expect(
      supplyParametersSchema.safeParse({ target_days: 14.5, lead_time_days: 7 })
        .success
    ).toBe(false)
    for (const box_multiple of [0, -1, 1.5, 10001, NaN])
      expect(supplyPackagingSchema.safeParse({ box_multiple }).success).toBe(
        false
      )
    expect(supplyPackagingSchema.parse({ box_multiple: 6 })).toEqual({
      box_multiple: 6
    })
  })
})
