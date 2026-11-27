import { expect, it } from 'vitest'

import { webApiOrigin } from '@/lib/webApiOrigin'

it('Wi-Fi приглашение использует API компьютера, а не localhost телефона', () => {
  expect(
    webApiOrigin(
      'http://localhost:8000/api/v1',
      'http://192.168.10.14:8081/invite',
      true
    )
  ).toBe('http://192.168.10.14:8000')
})
it('сохраняет явный адрес production API и не направляет локальный API на чужой домен', () => {
  expect(
    webApiOrigin(
      'https://api.perk.example/api/v1',
      'http://localhost:8081',
      true
    )
  ).toBe('https://api.perk.example')
  expect(
    webApiOrigin('http://localhost:8000', 'https://other.example', true)
  ).toBe('http://localhost:8000')
  expect(
    webApiOrigin('http://localhost:8000', 'http://192.168.1.10:8081', false)
  ).toBe('http://localhost:8000')
})
