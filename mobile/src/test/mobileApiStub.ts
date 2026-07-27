import { vi } from 'vitest'

import type { MobileApi } from '../services/api'

export function createMobileApiStub(overrides: Partial<MobileApi> = {}): MobileApi {
  return {
    activate: vi.fn(), refresh: vi.fn(), getMe: vi.fn(), logout: vi.fn(),
    getLearningProfile: vi.fn(), updateLearningProfile: vi.fn(), listSessions: vi.fn(),
    revokeSession: vi.fn(), exportOwnerData: vi.fn(), listBooks: vi.fn(), listChapters: vi.fn(),
    searchCards: vi.fn(), getCard: vi.fn(), enroll: vi.fn(), updateEnrollment: vi.fn(),
    updateChapterEnrollments: vi.fn(), getInsightSummary: vi.fn(), getInsightWorkload: vi.fn(),
    getWeakTopics: vi.fn(), getToday: vi.fn(), adjustTodayBudget: vi.fn(),
    createStudySession: vi.fn(), getNextTask: vi.fn(), submitReviewAttempt: vi.fn(),
    completeStudySession: vi.fn(), interruptStudySession: vi.fn(), resumeStudySession: vi.fn(),
    ...overrides
  }
}
