import { expect, test, vi } from 'vitest'

import { createNativeSessionStore } from './secureSession'

test('native session adapter maps the secure plugin without browser persistence', async () => {
  const plugin = {
    read: vi.fn().mockResolvedValue({
      accessToken: 'native-session-token',
      expiresAt: '2099-07-27T00:00:00Z'
    }),
    write: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined)
  }
  const store = createNativeSessionStore(plugin)

  expect(await store.read()).toEqual({
    accessToken: 'native-session-token',
    expiresAt: '2099-07-27T00:00:00Z'
  })
  await store.write({ accessToken: 'rotated-token', expiresAt: '2099-08-01T00:00:00Z' })
  await store.clear()

  expect(plugin.write).toHaveBeenCalledWith({
    accessToken: 'rotated-token',
    expiresAt: '2099-08-01T00:00:00Z'
  })
  expect(localStorage.length).toBe(0)
})
