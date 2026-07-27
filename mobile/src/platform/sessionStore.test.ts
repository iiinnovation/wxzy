import { expect, test } from 'vitest'

import { createMemorySessionStore } from './sessionStore'

test('memory session store writes and clears without browser persistence', async () => {
  const store = createMemorySessionStore()
  const session = { accessToken: 'memory-only-token', expiresAt: '2099-07-27T00:00:00Z' }

  await store.write(session)
  expect(await store.read()).toEqual(session)
  expect(localStorage.length).toBe(0)

  await store.clear()
  expect(await store.read()).toBeNull()
})
