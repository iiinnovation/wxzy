import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AppRuntime } from '../../app/runtime'
import { createMemorySessionStore } from '../../platform/sessionStore'
import { ApiError, type MobileApi, type StudySessionNext } from '../../services/api'
import { StudySessionPage } from './StudySessionPage'

const activeTask: StudySessionNext = {
  session: {
    id: 29,
    status: 'active',
    planned_task_count: 1,
    completed_task_count: 0,
    cursor_position: 0,
    interruption_reason: null
  },
  task: {
    plan_item: {
      id: 11,
      position: 0,
      item_type: 'due',
      enrollment_id: 3,
      card_id: 4,
      estimated_seconds: 90,
      reason_code: 'DUE',
      reason_detail: null,
      status: 'pending'
    },
    card: {
      id: 4,
      book_name: '中医基础理论',
      chapter: '阴阳学说',
      question: '阴阳的基本关系有哪些？',
      answer: '阴阳之间存在对立制约、互根互用、消长平衡与相互转化。',
      answer_points: ['对立制约', '互根互用'],
      source_excerpt: '阴阳者，一分为二也。',
      source_pages: [12]
    },
    card_revision: 2,
    review_state: {
      due_at: '2026-07-27T00:00:00Z',
      state: 'review',
      reps: 3
    }
  }
}

test('retries the exact same rating payload before advancing', async () => {
  const api = apiStub()
  vi.mocked(api.getNextTask)
    .mockResolvedValueOnce(activeTask)
    .mockResolvedValueOnce({
      session: { ...activeTask.session, completed_task_count: 1, cursor_position: 1 },
      task: null
    })
  vi.mocked(api.submitReviewAttempt)
    .mockRejectedValueOnce(new ApiError(0, 'NETWORK_ERROR', '无法连接服务器，请检查网络后重试'))
    .mockResolvedValueOnce(undefined)
  vi.mocked(api.completeStudySession).mockResolvedValue({
    ...activeTask.session,
    status: 'completed',
    completed_task_count: 1,
    cursor_position: 1
  })

  render(<StudySessionPage runtime={runtimeWith(api)} sessionId={29} />)

  expect(await screen.findByRole('heading', { name: '阴阳的基本关系有哪些？' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '查看答案' }))
  fireEvent.click(screen.getByRole('checkbox', { name: '对立制约' }))
  fireEvent.click(screen.getByRole('button', { name: /3良好/ }))

  expect(await screen.findByRole('alert')).toHaveTextContent('无法连接服务器')
  const firstPayload = vi.mocked(api.submitReviewAttempt).mock.calls[0][1]
  expect(firstPayload.rating).toBe(3)
  expect(firstPayload.answer_payload.points_recalled).toBe(1)

  fireEvent.click(screen.getByRole('button', { name: '原样重试' }))
  expect(await screen.findByRole('heading', { name: '今日学习完成' })).toBeInTheDocument()
  const secondPayload = vi.mocked(api.submitReviewAttempt).mock.calls[1][1]
  expect(secondPayload).toBe(firstPayload)
  expect(secondPayload.client_attempt_id).toBe(firstPayload.client_attempt_id)
  expect(api.getNextTask).toHaveBeenCalledTimes(2)
})

test('interrupts an active session before handling the Android back gesture', async () => {
  const api = apiStub()
  vi.mocked(api.getNextTask).mockResolvedValue(activeTask)
  vi.mocked(api.interruptStudySession).mockResolvedValue({ ...activeTask.session, status: 'interrupted' })
  render(<StudySessionPage runtime={runtimeWith(api)} sessionId={29} />)

  expect(await screen.findByRole('heading', { name: '阴阳的基本关系有哪些？' })).toBeInTheDocument()
  fireEvent(window, new Event('wenxi:study-back'))

  await vi.waitFor(() => expect(api.interruptStudySession).toHaveBeenCalledWith('session-token', 29))
  expect(window.location.hash).toBe('#/today')
})

function runtimeWith(api: MobileApi): AppRuntime {
  return {
    api,
    sessionStore: createMemorySessionStore({
      accessToken: 'session-token',
      expiresAt: '2099-07-27T00:00:00Z'
    })
  }
}

function apiStub(): MobileApi {
  return {
    activate: vi.fn(), refresh: vi.fn(), getMe: vi.fn(), logout: vi.fn(),
    getLearningProfile: vi.fn(), updateLearningProfile: vi.fn(), listSessions: vi.fn(),
    revokeSession: vi.fn(), exportOwnerData: vi.fn(), listBooks: vi.fn(), listChapters: vi.fn(),
    searchCards: vi.fn(), getCard: vi.fn(), enroll: vi.fn(), updateEnrollment: vi.fn(),
    updateChapterEnrollments: vi.fn(), getInsightSummary: vi.fn(), getInsightWorkload: vi.fn(), getWeakTopics: vi.fn(),
    getToday: vi.fn(), adjustTodayBudget: vi.fn(), createStudySession: vi.fn(),
    getNextTask: vi.fn(), submitReviewAttempt: vi.fn(), completeStudySession: vi.fn(),
    interruptStudySession: vi.fn(), resumeStudySession: vi.fn()
  }
}
