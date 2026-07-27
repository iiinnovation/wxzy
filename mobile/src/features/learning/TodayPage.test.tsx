import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AppRuntime } from '../../app/runtime'
import { createMemorySessionStore } from '../../platform/sessionStore'
import type { DailyPlan, MobileApi } from '../../services/api'
import { TodayPage } from './TodayPage'

const plan: DailyPlan = {
  id: 7,
  plan_date: '2026-07-27',
  budget_minutes: 20,
  adjusted_budget_minutes: null,
  effective_budget_minutes: 20,
  estimated_minutes: 8,
  due_count: 1,
  new_count: 0,
  weak_count: 0,
  new_cards_paused: false,
  pause_reasons: [],
  items: [
    {
      id: 11,
      position: 0,
      item_type: 'due',
      enrollment_id: 3,
      card_id: 4,
      estimated_seconds: 90,
      reason_code: 'DUE',
      reason_detail: null,
      status: 'pending'
    }
  ]
}

test('loads today, adjusts the budget, and starts the plan session', async () => {
  const api = apiStub()
  vi.mocked(api.getToday).mockResolvedValue(plan)
  vi.mocked(api.adjustTodayBudget).mockResolvedValue({
    ...plan,
    adjusted_budget_minutes: 30,
    effective_budget_minutes: 30
  })
  vi.mocked(api.createStudySession).mockResolvedValue({
    id: 29,
    status: 'active',
    planned_task_count: 1,
    completed_task_count: 0,
    cursor_position: 0,
    interruption_reason: null
  })
  const runtime = runtimeWith(api)

  render(<TodayPage runtime={runtime} />)

  expect(await screen.findByRole('heading', { name: '今日学习' })).toBeInTheDocument()
  expect(screen.getAllByText('到期复习')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: '30' }))
  await waitFor(() => expect(api.adjustTodayBudget).toHaveBeenCalledWith('session-token', 30))
  await waitFor(() => expect(screen.getByRole('button', { name: '开始今日学习' })).toBeEnabled())

  fireEvent.click(screen.getByRole('button', { name: '开始今日学习' }))
  await waitFor(() => expect(window.location.hash).toBe('#/study/29'))
  expect(api.createStudySession).toHaveBeenCalledWith('session-token', 7)
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
