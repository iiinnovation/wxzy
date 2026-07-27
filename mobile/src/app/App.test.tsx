import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'

import { createMemorySessionStore, type SessionStore } from '../platform/sessionStore'
import { ApiError, type DailyPlan, type MobileApi, type Owner, type SessionToken } from '../services/api'
import { App } from './App'
import type { AppRuntime } from './runtime'

const owner: Owner = {
  id: 1,
  status: 'active',
  display_name: '学习者',
  timezone: 'Asia/Shanghai'
}

const issuedSession: SessionToken = {
  access_token: 'test-session-token-with-more-than-32-characters',
  token_type: 'bearer',
  expires_at: '2099-07-27T00:00:00Z',
  owner
}

const emptyPlan: DailyPlan = {
  id: 1,
  plan_date: '2026-07-27',
  budget_minutes: 20,
  adjusted_budget_minutes: null,
  effective_budget_minutes: 20,
  estimated_minutes: 0,
  due_count: 0,
  new_count: 0,
  weak_count: 0,
  new_cards_paused: false,
  pause_reasons: [],
  items: []
}

function createRuntime(options?: {
  store?: SessionStore
  activate?: MobileApi['activate']
  refresh?: MobileApi['refresh']
  getMe?: MobileApi['getMe']
}): AppRuntime {
  return {
    sessionStore: options?.store ?? createMemorySessionStore(),
    api: {
      activate: options?.activate ?? vi.fn().mockResolvedValue(issuedSession),
      refresh: options?.refresh ?? vi.fn().mockResolvedValue(issuedSession),
      getMe: options?.getMe ?? vi.fn().mockResolvedValue(owner),
      logout: vi.fn().mockResolvedValue(undefined),
      getLearningProfile: vi.fn().mockRejectedValue(new Error('profile not required by this test')),
      updateLearningProfile: vi.fn(),
      listSessions: vi.fn(),
      revokeSession: vi.fn(),
      exportOwnerData: vi.fn(),
      listBooks: vi.fn(),
      listChapters: vi.fn(),
      searchCards: vi.fn(),
      getCard: vi.fn(),
      enroll: vi.fn(),
      updateEnrollment: vi.fn(),
      updateChapterEnrollments: vi.fn(),
      getInsightSummary: vi.fn(),
      getInsightWorkload: vi.fn(),
      getWeakTopics: vi.fn(),
      getToday: vi.fn().mockResolvedValue(emptyPlan),
      adjustTodayBudget: vi.fn(),
      createStudySession: vi.fn(),
      getNextTask: vi.fn(),
      submitReviewAttempt: vi.fn(),
      completeStudySession: vi.fn(),
      interruptStudySession: vi.fn(),
      resumeStudySession: vi.fn()
    }
  }
}

beforeEach(() => {
  window.location.hash = '#/activate'
})

test('opens on the device activation workflow without a stored session', async () => {
  render(<App runtime={createRuntime()} />)

  expect(await screen.findByRole('heading', { name: '温习' })).toBeInTheDocument()
  expect(screen.getByLabelText('一次性激活码')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '激活并进入今日学习' })).toBeDisabled()
  expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
})

test('activates once, stores the session, and enters today', async () => {
  const activate = vi.fn().mockResolvedValue(issuedSession)
  const store = createMemorySessionStore()
  render(<App runtime={createRuntime({ activate, store })} />)

  fireEvent.change(await screen.findByLabelText('一次性激活码'), {
    target: { value: '  one-time-code  ' }
  })
  fireEvent.submit(screen.getByRole('button', { name: '激活并进入今日学习' }).closest('form')!)

  expect(await screen.findByRole('heading', { name: '今日学习' })).toBeInTheDocument()
  expect(activate).toHaveBeenCalledWith('one-time-code', 'Xiaomi 17 Pro')
  expect(await store.read()).toEqual({
    accessToken: issuedSession.access_token,
    expiresAt: issuedSession.expires_at
  })
  expect(screen.getByRole('navigation', { name: '主要导航' })).toBeInTheDocument()
})

test('shows a safe activation error and allows retry', async () => {
  const activate = vi
    .fn()
    .mockRejectedValueOnce(new ApiError(400, 'MOBILE_ACTIVATION_INVALID', '设备激活码无效或已过期'))
    .mockResolvedValueOnce(issuedSession)
  render(<App runtime={createRuntime({ activate })} />)

  const input = await screen.findByLabelText('一次性激活码')
  fireEvent.change(input, { target: { value: 'invalid-code' } })
  fireEvent.click(screen.getByRole('button', { name: '激活并进入今日学习' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('设备激活码无效或已过期')
  fireEvent.click(screen.getByRole('button', { name: '激活并进入今日学习' }))
  expect(await screen.findByRole('heading', { name: '今日学习' })).toBeInTheDocument()
  expect(activate).toHaveBeenCalledTimes(2)
})

test('restores a valid stored session before showing the app shell', async () => {
  const getMe = vi.fn().mockResolvedValue(owner)
  const store = createMemorySessionStore({
    accessToken: issuedSession.access_token,
    expiresAt: issuedSession.expires_at
  })
  render(<App runtime={createRuntime({ store, getMe })} />)

  expect(await screen.findByRole('heading', { name: '今日学习' })).toBeInTheDocument()
  expect(getMe).toHaveBeenCalledWith(issuedSession.access_token)
})

test('clears an unauthorized stored session and returns to activation', async () => {
  const store = createMemorySessionStore({
    accessToken: issuedSession.access_token,
    expiresAt: issuedSession.expires_at
  })
  const getMe = vi.fn().mockRejectedValue(new ApiError(401, 'UNAUTHORIZED', '连接凭证无效'))
  render(<App runtime={createRuntime({ store, getMe })} />)

  expect(await screen.findByLabelText('一次性激活码')).toBeInTheDocument()
  await waitFor(async () => expect(await store.read()).toBeNull())
})

test('clears a near-expiry session when rotation is rejected', async () => {
  const store = createMemorySessionStore({
    accessToken: issuedSession.access_token,
    expiresAt: new Date(Date.now() + 60_000).toISOString()
  })
  const refresh = vi.fn().mockRejectedValue(new ApiError(401, 'UNAUTHORIZED', '设备会话已失效，请重新激活'))
  render(<App runtime={createRuntime({ store, refresh })} />)

  expect(await screen.findByLabelText('一次性激活码')).toBeInTheDocument()
  expect(refresh).toHaveBeenCalledWith(issuedSession.access_token)
  await waitFor(async () => expect(await store.read()).toBeNull())
})

test('revalidates and clears a revoked session when the WebView returns to foreground', async () => {
  const store = createMemorySessionStore({ accessToken: issuedSession.access_token, expiresAt: issuedSession.expires_at })
  const getMe = vi.fn().mockResolvedValueOnce(owner).mockRejectedValue(new ApiError(401, 'UNAUTHORIZED', 'revoked'))
  const refresh = vi.fn().mockRejectedValue(new ApiError(401, 'UNAUTHORIZED', 'revoked'))
  render(<App runtime={createRuntime({ store, getMe, refresh })} />)
  expect(await screen.findByRole('heading', { name: '今日学习' })).toBeInTheDocument()

  fireEvent(document, new Event('visibilitychange'))

  expect(await screen.findByLabelText('一次性激活码')).toBeInTheDocument()
  await waitFor(async () => expect(await store.read()).toBeNull())
})
