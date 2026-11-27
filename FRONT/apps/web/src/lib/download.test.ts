import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import { downloadResponse } from './download'

describe('file response errors', () => {
  it('keeps status and parses JSON blob details for step-up and useful errors', async () => {
    const error = new AxiosError('409')
    error.response = {
      status: 409,
      data: new Blob([JSON.stringify({ detail: 'План изменился' })], {
        type: 'application/json'
      }),
      headers: { 'content-type': 'application/json' }
    } as AxiosError['response']
    await expect(downloadResponse(Promise.reject(error))).rejects.toBe(error)
    expect(error.response?.status).toBe(409)
    expect(error.response?.data).toEqual({ detail: 'План изменился' })
  })
  it('returns successful file bytes unchanged', async () => {
    const blob = new Blob(['file'])
    expect(await downloadResponse(Promise.resolve(blob))).toBe(blob)
  })
})
