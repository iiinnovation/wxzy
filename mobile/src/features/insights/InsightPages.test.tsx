import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AppRuntime } from '../../app/runtime'
import { createMemorySessionStore } from '../../platform/sessionStore'
import { createMobileApiStub } from '../../test/mobileApiStub'
import { InsightsPage } from './InsightPages'

test('renders progress, workload, subject trends, and weak-topic entry points', async () => {
  const api = createMobileApiStub({
    getInsightSummary: vi.fn().mockResolvedValue({ user_id: 1, timezone: 'Asia/Shanghai', local_date: '2026-07-27', generated_at: '2026-07-27T00:00:00Z', study_days: 6, total_actual_minutes: 120, total_review_count: 30, total_new_count: 8, today_actual_minutes: 20, today_review_count: 4, today_new_count: 1, current_due_count: 2, backlog_count: 1, content: { document_page_count: 100, covered_page_count: 80, coverage_ratio: 0.8, published_card_count: 71, enrolled_card_count: 20, active_card_count: 18, mastered_card_count: 7 }, subjects: [{ subject: '基础理论', published_card_count: 18, enrolled_card_count: 8, active_card_count: 7, mastered_card_count: 3, attempt_count_30d: 12, again_count_30d: 2, hard_count_30d: 3, success_rate_30d: 0.8, trend: 'improving' }] }),
    getInsightWorkload: vi.fn().mockResolvedValue({ user_id: 1, timezone: 'Asia/Shanghai', generated_at: '2026-07-27T00:00:00Z', review_seconds_estimate: 90, total_due_count: 2, total_estimated_minutes: 5, total_budget_minutes: 20, overloaded: false, days: [{ local_date: '2026-07-27', due_count: 2, overdue_count: 0, estimated_minutes: 5, budget_minutes: 20, overloaded: false }] }),
    getWeakTopics: vi.fn().mockResolvedValue({ user_id: 1, generated_at: '2026-07-27T00:00:00Z', total: 1, offset: 0, limit: 5, has_more: false, items: [{ card_id: 9, card_revision: 1, topic: '阴阳互根', tags: [], severity_score: 20, reason_code: 'repeated_again', reason_detail: '多次错误', signals: [{ code: 'repeated_again', detail: '多次错误' }], actions: [], evidence: { attempt_count: 3, again_count: 2, hard_count: 0, slow_hard_count: 0, issue_types: [], confusion_tags: [], related_card_ids: [], latest_failure_at: null }, source: { card_id: 9, card_revision: 1, book_id: 3, book_name: '中医基础理论', subject: '基础理论', chapter: '阴阳学说', section: null, source_id: 1, excerpt: '原文', pdf_page_start: 12, pdf_page_end: 12, printed_page_start_label: null, printed_page_end_label: null } }] })
  })
  const runtime: AppRuntime = { api, sessionStore: createMemorySessionStore({ accessToken: 'token', expiresAt: '2099-01-01T00:00:00Z' }) }
  render(<InsightsPage runtime={runtime} />)

  expect(await screen.findByText('内容与掌握')).toBeInTheDocument()
  expect(screen.getByText('正在改善')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /阴阳互根/ })).toHaveAttribute('href', '#/weak/9')
  expect(screen.getByRole('link', { name: /本周混合测试/ })).toHaveAttribute('href', '#/weekly')
})
