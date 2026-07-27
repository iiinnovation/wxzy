import { expect, test, vi } from 'vitest'

import { ApiError, createApiClient } from './api'

test('activation uses the v1 contract without putting the code in the URL', async () => {
  const fetchRequest = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        access_token: 'test-session-token-with-more-than-32-characters',
        token_type: 'bearer',
        expires_at: '2099-07-27T00:00:00Z',
        owner: { id: 1, status: 'active', display_name: null, timezone: 'Asia/Shanghai' }
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } }
    )
  )
  const api = createApiClient({ baseUrl: 'https://api.example.test/', fetch: fetchRequest })

  await api.activate('one-time-code', 'OPPO Find X7 Pro')

  expect(fetchRequest).toHaveBeenCalledTimes(1)
  const [url, init] = fetchRequest.mock.calls[0]
  expect(url).toBe('https://api.example.test/api/v1/auth/mobile/activate')
  expect(url).not.toContain('one-time-code')
  expect(JSON.parse(init.body as string)).toEqual({
    activation_code: 'one-time-code',
    device_label: 'OPPO Find X7 Pro'
  })
})

test('maps the server error envelope without echoing request data', async () => {
  const fetchRequest = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        code: 'MOBILE_ACTIVATION_INVALID',
        message: '设备激活码无效或已过期',
        request_id: 'req_mobile_failure'
      }),
      { status: 400, headers: { 'Content-Type': 'application/json' } }
    )
  )
  const api = createApiClient({ baseUrl: 'https://api.example.test', fetch: fetchRequest })

  await expect(api.activate('secret-value', null)).rejects.toEqual(
    new ApiError(400, 'MOBILE_ACTIVATION_INVALID', '设备激活码无效或已过期', 'req_mobile_failure')
  )
})

test('maps transport failures to a retryable network error', async () => {
  const api = createApiClient({
    baseUrl: 'https://api.example.test',
    fetch: vi.fn().mockRejectedValue(new TypeError('offline'))
  })

  await expect(api.getMe('session-token')).rejects.toMatchObject({
    status: 0,
    code: 'NETWORK_ERROR'
  })
})
