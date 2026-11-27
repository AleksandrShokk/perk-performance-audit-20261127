import { describe, expect, it } from 'vitest'

import { connectOzonSchema, replaceOzonKeySchema } from '@app/schemas'

import { reportingConnections } from '@/features/workspace/model/reportingConnections'

const valid = {
  name: 'Store',
  client_id: '123456',
  api_key: 'synthetic-never-real-key'
}

describe('Ozon connection forms', () => {
  it('normalizes pasted credentials while keeping Client ID as a string', () => {
    const parsed = connectOzonSchema.parse({
      name: ' Store ',
      client_id: ' 123456 ',
      api_key: ` ${valid.api_key} `
    })
    expect(parsed).toEqual(valid)
  })
  it.each([
    { name: '  ' },
    { client_id: '-1' },
    { client_id: 'abc' },
    { api_key: '' }
  ])('rejects incomplete connection values %j', invalid => {
    expect(connectOzonSchema.safeParse({ ...valid, ...invalid }).success).toBe(
      false
    )
  })
  it('key rotation only asks for a new key, without changing cabinet identity', () => {
    expect(replaceOzonKeySchema.parse({ api_key: valid.api_key })).toEqual({
      api_key: valid.api_key
    })
  })
})

describe('stores available for reporting', () => {
  it('keeps unfinished Ozon connections out of WB reports', () => {
    const connections = [
      { id: 'wb', marketplace: 'wildberries', reports_available: true },
      { id: 'ozon', marketplace: 'ozon', reports_available: false }
    ]
    expect(reportingConnections(connections).map(store => store.id)).toEqual([
      'wb'
    ])
    expect(connections).toHaveLength(2) // Management still shows both connections.
  })
  it('supports legacy WB responses and future enabled Ozon read models', () => {
    const connections = [
      { marketplace: 'wildberries' },
      { marketplace: 'ozon' },
      { marketplace: 'ozon', reports_available: true },
      { marketplace: 'wildberries', reports_available: false }
    ]
    expect(reportingConnections(connections)).toEqual([
      connections[0],
      connections[2]
    ])
  })
})
