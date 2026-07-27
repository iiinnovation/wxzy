import { expect, test, vi } from 'vitest'

import { createMemorySessionStore } from '../platform/sessionStore'
import { ApiError, type SessionToken } from '../services/api'
import { createMobileApiStub } from '../test/mobileApiStub'
import type { AppRuntime } from './runtime'
import { getAccessToken, withSession } from './session'

const refreshed: SessionToken = {
  access_token: 'refreshed-session-token-with-more-than-32-chars', token_type: 'bearer',
  expires_at: '2099-08-01T00:00:00Z',
  owner: { id: 1, status: 'active', display_name: null, timezone: 'Asia/Shanghai' }
}

test('refreshes a session that is near expiry and persists the rotated token', async () => {
  const store = createMemorySessionStore({ accessToken: 'old-token', expiresAt: new Date(Date.now() + 60_000).toISOString() })
  const api = createMobileApiStub({ refresh: vi.fn().mockResolvedValue(refreshed) })
  const runtime: AppRuntime = { api, sessionStore: store }

  expect(await getAccessToken(runtime)).toBe(refreshed.access_token)
  expect(api.refresh).toHaveBeenCalledWith('old-token')
  expect(await store.read()).toEqual({ accessToken: refreshed.access_token, expiresAt: refreshed.expires_at })
})

test('refreshes once and retries an authenticated operation after 401', async () => {
  const store = createMemorySessionStore({ accessToken: 'current-token', expiresAt: '2099-07-27T00:00:00Z' })
  const api = createMobileApiStub({ refresh: vi.fn().mockResolvedValue(refreshed) })
  const operation = vi.fn().mockRejectedValueOnce(new ApiError(401, 'UNAUTHORIZED', 'expired')).mockResolvedValueOnce('ok')

  await expect(withSession({ api, sessionStore: store }, operation)).resolves.toBe('ok')
  expect(operation).toHaveBeenNthCalledWith(1, 'current-token')
  expect(operation).toHaveBeenNthCalledWith(2, refreshed.access_token)
})
