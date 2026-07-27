import { expect, test, type Page, type Route } from '@playwright/test'

test('all four tabs and task pages are usable at the target mobile viewport', async ({ page }) => {
  await mockApi(page)
  await page.goto('/#/activate')
  await page.getByLabel('一次性激活码').fill('controlled-test-code')
  await page.getByRole('button', { name: '激活并进入今日学习' }).click()
  await expect(page.getByRole('heading', { name: '今日学习' })).toBeVisible()

  await page.getByRole('link', { name: '学科' }).click()
  await expect(page.getByText('中医基础理论')).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'test-results/mobile-subjects.png', fullPage: true })
  await page.getByRole('link', { name: /中医基础理论/ }).click()
  await expect(page.getByRole('heading', { name: '阴阳学说' })).toBeVisible()
  await page.getByRole('button', { name: '加入本章其余卡片' }).click()
  await expect(page.getByText('已加入 3 张卡片')).toBeVisible()
  await page.getByRole('link', { name: /阴阳的基本关系/ }).click()
  await expect(page.getByText('阴阳之间存在对立制约')).toBeVisible()
  await expect(page.getByText('阴阳者，一分为二也。')).toBeVisible()
  await assertNoHorizontalOverflow(page)

  await page.goto('/#/insights')
  await expect(page.getByText('内容与掌握')).toBeVisible()
  await expect(page.getByText('正在改善')).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'test-results/mobile-insights.png', fullPage: true })
  await page.getByRole('link', { name: /阴阳互根/ }).click()
  await expect(page.getByRole('heading', { name: '阴阳互根' })).toBeVisible()
  await page.goto('/#/weekly')
  await expect(page.getByRole('heading', { name: '本周混合测试' })).toBeVisible()

  await page.goto('/#/me')
  await expect(page.getByText('OPPO Find X7 Pro · 当前设备')).toBeVisible()
  await page.getByRole('link', { name: '编辑档案' }).click()
  await expect(page.getByRole('heading', { name: '档案设置' })).toBeVisible()
  await page.getByLabel('每日分钟').fill('30')
  await page.getByRole('button', { name: '保存档案' }).click()
  await expect(page.getByText('档案已保存')).toBeVisible()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: 'test-results/mobile-profile.png', fullPage: true })
  await expect(page.getByText('移动端学习数据已连接')).toHaveCount(0)
})

async function assertNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    const body = responseFor(path, method)
    await fulfill(route, body, path.includes('/sessions/') && method === 'DELETE' ? 204 : 200)
  })
}

async function fulfill(route: Route, body: unknown, status: number) {
  await route.fulfill({ status, contentType: 'application/json', body: status === 204 ? '' : JSON.stringify(body) })
}

function responseFor(path: string, method: string): unknown {
  if (path.endsWith('/auth/mobile/activate')) return { access_token: 'test-session-token-with-more-than-32-characters', token_type: 'bearer', expires_at: '2099-01-01T00:00:00Z', owner }
  if (path.endsWith('/me/learning-profile')) return method === 'PUT' ? { ...profile, daily_minutes: 30, updated_at: '2026-07-27T11:00:00Z' } : profile
  if (path.endsWith('/catalog/books')) return [book]
  if (path.endsWith('/catalog/books/3/chapters')) return [chapter]
  if (path.endsWith('/catalog/cards/9')) return cardDetail
  if (path.endsWith('/catalog/cards')) return { total: 1, offset: 0, limit: 20, has_more: false, items: [card] }
  if (path.endsWith('/enrollments')) return { scope: 'chapter', created_count: 3, existing_count: 2, card_ids: [9, 10, 11], enrollments: [] }
  if (path.endsWith('/insights/summary')) return summary
  if (path.endsWith('/insights/workload')) return workload
  if (path.endsWith('/insights/weak-topics')) return weakPage
  if (path.endsWith('/learning/today')) return today
  if (path.endsWith('/me/sessions')) return { items: [{ id: 1, device_label: 'OPPO Find X7 Pro', created_at: '2026-07-27T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', revoked_at: null, status: 'active', current: true }] }
  if (path.endsWith('/me')) return owner
  return {}
}

const owner = { id: 1, status: 'active', display_name: '学习者', timezone: 'Asia/Shanghai' }
const profile = { id: 1, user_id: 1, goal_type: 'daily_learning', target_date: null, daily_minutes: 20, study_days: [true, true, true, true, true, false, false], desired_retention: 0.9, new_card_ceiling: 5, subject_priorities: { 基础理论: 4 }, initial_self_assessment: { 基础理论: 3 }, onboarding_completed_at: '2026-07-01T00:00:00Z', created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-27T10:00:00Z', display_name: '学习者', timezone: 'Asia/Shanghai' }
const book = { id: 3, name: '中医基础理论', subject: '基础理论', chapter_count: 1, published_card_count: 5, enrolled_card_count: 2, queued_card_count: 1, active_card_count: 1, suspended_card_count: 0, mastered_card_count: 0 }
const chapter = { id: 8, parent_id: null, title: '阴阳学说', level: 0, sort_order: 1, pdf_page_start: 10, pdf_page_end: 30, published_card_count: 5, enrolled_card_count: 2, queued_card_count: 1, active_card_count: 1, suspended_card_count: 0, mastered_card_count: 0 }
const card = { id: 9, external_id: 'card-9', book_id: 3, book_name: '中医基础理论', chapter: '阴阳学说', section: null, card_type: 'qa', question: '阴阳的基本关系有哪些？', answer: '阴阳之间存在对立制约、互根互用、消长平衡与相互转化。', answer_points: ['对立制约', '互根互用'], source_excerpt: '阴阳者，一分为二也。', source_pages: [12], tags: ['阴阳'], status: 'published', confidence: 1 }
const cardDetail = { card, enrollment_id: null, enrollment_status: null, review_state: null, mastered: false, sources: [{ id: 1, card_id: 9, citation_order: 0, document_key: 'jichu', document_title: '中医基础理论', document_version_id: 1, chunk_key: 'chunk-1', chapter_path: ['阴阳学说'], excerpt: '阴阳者，一分为二也。', pdf_page_index_start: 11, pdf_page_index_end: 11, pdf_page_number_start: 12, pdf_page_number_end: 12, printed_page_start_label: null, printed_page_end_label: null }] }
const summary = { user_id: 1, timezone: 'Asia/Shanghai', local_date: '2026-07-27', generated_at: '2026-07-27T00:00:00Z', study_days: 6, total_actual_minutes: 120, total_review_count: 30, total_new_count: 8, today_actual_minutes: 20, today_review_count: 4, today_new_count: 1, current_due_count: 2, backlog_count: 1, content: { document_page_count: 100, covered_page_count: 80, coverage_ratio: 0.8, published_card_count: 71, enrolled_card_count: 20, active_card_count: 18, mastered_card_count: 7 }, subjects: [{ subject: '基础理论', published_card_count: 18, enrolled_card_count: 8, active_card_count: 7, mastered_card_count: 3, attempt_count_30d: 12, again_count_30d: 2, hard_count_30d: 3, success_rate_30d: 0.8, trend: 'improving' }] }
const workload = { user_id: 1, timezone: 'Asia/Shanghai', generated_at: '2026-07-27T00:00:00Z', review_seconds_estimate: 90, total_due_count: 2, total_estimated_minutes: 5, total_budget_minutes: 20, overloaded: false, days: [{ local_date: '2026-07-27', due_count: 2, overdue_count: 0, estimated_minutes: 5, budget_minutes: 20, overloaded: false }] }
const weak = { card_id: 9, card_revision: 1, topic: '阴阳互根', tags: [], severity_score: 20, reason_code: 'repeated_again', reason_detail: '多次错误', signals: [{ code: 'repeated_again', detail: '多次错误' }], actions: [{ code: 'reread_source', reason: '重读来源' }], evidence: { attempt_count: 3, again_count: 2, hard_count: 0, slow_hard_count: 0, issue_types: [], confusion_tags: [], related_card_ids: [], latest_failure_at: null }, source: { card_id: 9, card_revision: 1, book_id: 3, book_name: '中医基础理论', subject: '基础理论', chapter: '阴阳学说', section: null, source_id: 1, excerpt: '阴阳者，一分为二也。', pdf_page_start: 12, pdf_page_end: 12, printed_page_start_label: null, printed_page_end_label: null } }
const weakPage = { user_id: 1, generated_at: '2026-07-27T00:00:00Z', total: 1, offset: 0, limit: 20, has_more: false, items: [weak] }
const today = { id: 1, plan_date: '2026-07-27', budget_minutes: 20, adjusted_budget_minutes: null, effective_budget_minutes: 20, estimated_minutes: 4, due_count: 0, new_count: 0, weak_count: 1, new_cards_paused: false, pause_reasons: [], items: [{ id: 4, position: 0, item_type: 'mixed_weekly', enrollment_id: 1, card_id: 9, estimated_seconds: 90, reason_code: 'WEEKLY', reason_detail: null, status: 'pending' }] }
