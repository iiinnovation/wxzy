export interface Owner {
  id: number
  status: string
  display_name: string | null
  timezone: string
}

export interface SessionToken {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  owner: Owner
}

export interface LearningProfile {
  id: number
  user_id: number
  goal_type: 'daily_learning' | 'exam' | 'focused'
  target_date: string | null
  daily_minutes: number
  study_days: boolean[]
  desired_retention: number
  new_card_ceiling: number
  subject_priorities: Record<string, number>
  initial_self_assessment: Record<string, number>
  onboarding_completed_at: string | null
  created_at: string
  updated_at: string
  display_name: string | null
  timezone: string
}

export interface LearningProfileUpdate {
  expected_updated_at: string
  goal_type: LearningProfile['goal_type']
  target_date: string | null
  daily_minutes: number
  study_days: boolean[]
  desired_retention: number
  new_card_ceiling: number
  subject_priorities: Record<string, number>
  initial_self_assessment: Record<string, number>
  onboarding_completed?: boolean
  display_name: string | null
  timezone: string
}

export interface SessionDevice {
  id: number
  device_label: string | null
  created_at: string
  expires_at: string
  revoked_at: string | null
  status: 'active' | 'expired' | 'revoked'
  current: boolean
}

export interface OwnerDataExport {
  schema_version: 'wxzy-owner-export-v1'
  generated_at: string
  backup_status: 'not_configured'
  owner: Owner
  learning_profile: Record<string, unknown>
  sessions: SessionDevice[]
  learning_data: Record<string, Array<Record<string, unknown>>>
}

export interface CatalogBook {
  id: number
  name: string
  subject: string | null
  chapter_count: number
  published_card_count: number
  enrolled_card_count: number
  queued_card_count: number
  active_card_count: number
  suspended_card_count: number
  mastered_card_count: number
}

export interface CatalogChapter {
  id: number
  parent_id: number | null
  title: string
  level: number
  sort_order: number
  pdf_page_start: number
  pdf_page_end: number
  published_card_count: number
  enrolled_card_count: number
  queued_card_count: number
  active_card_count: number
  suspended_card_count: number
  mastered_card_count: number
}

export interface CatalogCard {
  id: number
  external_id: string
  book_id: number
  book_name: string | null
  chapter: string | null
  section: string | null
  card_type: string
  question: string
  answer: string
  answer_points: string[]
  source_excerpt: string
  source_pages: number[]
  tags: string[]
  status: string
  confidence: number | null
}

export interface CardSource {
  id: number
  card_id: number
  citation_order: number
  document_key: string
  document_title: string
  document_version_id: number
  chunk_key: string
  chapter_path: string[]
  excerpt: string
  pdf_page_index_start: number
  pdf_page_index_end: number
  pdf_page_number_start: number
  pdf_page_number_end: number
  printed_page_start_label: string | null
  printed_page_end_label: string | null
}

export interface CatalogCardPage {
  total: number
  offset: number
  limit: number
  has_more: boolean
  items: CatalogCard[]
}

export interface CatalogCardDetail {
  card: CatalogCard
  sources: CardSource[]
  enrollment_id: number | null
  enrollment_status: 'queued' | 'active' | 'suspended' | 'retired' | null
  review_state: string | null
  mastered: boolean
}

export interface EnrollmentBatch {
  scope: 'card' | 'chapter' | 'book'
  created_count: number
  existing_count: number
  card_ids: number[]
}

export interface ChapterEnrollmentResult {
  chapter_id: number
  status: 'active' | 'suspended'
  updated_count: number
  unchanged_count: number
  ignored_count: number
}

export interface InsightContentProgress {
  document_page_count: number
  covered_page_count: number
  coverage_ratio: number
  published_card_count: number
  enrolled_card_count: number
  active_card_count: number
  mastered_card_count: number
}

export interface InsightSubjectTrend {
  subject: string
  published_card_count: number
  enrolled_card_count: number
  active_card_count: number
  mastered_card_count: number
  attempt_count_30d: number
  again_count_30d: number
  hard_count_30d: number
  success_rate_30d: number | null
  trend: 'insufficient' | 'improving' | 'stable' | 'declining'
}

export interface InsightSummary {
  user_id: number
  timezone: string
  local_date: string
  generated_at: string
  study_days: number
  total_actual_minutes: number
  total_review_count: number
  total_new_count: number
  today_actual_minutes: number
  today_review_count: number
  today_new_count: number
  current_due_count: number
  backlog_count: number
  content: InsightContentProgress
  subjects: InsightSubjectTrend[]
}

export interface InsightWorkloadDay {
  local_date: string
  due_count: number
  overdue_count: number
  estimated_minutes: number
  budget_minutes: number
  overloaded: boolean
}

export interface InsightWorkload {
  user_id: number
  timezone: string
  generated_at: string
  review_seconds_estimate: number
  total_due_count: number
  total_estimated_minutes: number
  total_budget_minutes: number
  overloaded: boolean
  days: InsightWorkloadDay[]
}

export interface RepairSuggestion {
  card_id: number
  card_revision: number
  topic: string
  tags: string[]
  severity_score: number
  reason_code: string
  reason_detail: string
  signals: Array<{ code: string; detail: string }>
  actions: Array<{ code: string; reason: string }>
  evidence: {
    attempt_count: number
    again_count: number
    hard_count: number
    slow_hard_count: number
    issue_types: string[]
    confusion_tags: string[]
    related_card_ids: number[]
    latest_failure_at: string | null
  }
  source: {
    card_id: number
    card_revision: number
    book_id: number
    book_name: string
    subject: string | null
    chapter: string | null
    section: string | null
    source_id: number | null
    excerpt: string
    pdf_page_start: number | null
    pdf_page_end: number | null
    printed_page_start_label: string | null
    printed_page_end_label: string | null
  }
}

export interface WeakTopicPage {
  user_id: number
  generated_at: string
  total: number
  offset: number
  limit: number
  has_more: boolean
  items: RepairSuggestion[]
}

export interface DailyPlanItem {
  id: number
  position: number
  item_type: string
  enrollment_id: number
  card_id: number
  estimated_seconds: number
  reason_code: string
  reason_detail: string | null
  status: 'pending' | 'completed' | 'skipped'
}

export interface DailyPlan {
  id: number
  plan_date: string
  budget_minutes: number
  adjusted_budget_minutes: number | null
  effective_budget_minutes: number
  estimated_minutes: number
  due_count: number
  new_count: number
  weak_count: number
  new_cards_paused: boolean
  pause_reasons: string[]
  items: DailyPlanItem[]
}

export interface StudySession {
  id: number
  status: 'planned' | 'active' | 'completed' | 'interrupted' | 'cancelled'
  planned_task_count: number
  completed_task_count: number
  cursor_position: number
  interruption_reason: string | null
}

export interface StudyTask {
  plan_item: DailyPlanItem
  card: {
    id: number
    book_name: string | null
    chapter: string | null
    question: string
    answer: string
    answer_points: string[]
    source_excerpt: string
    source_pages: number[]
  }
  card_revision: number
  review_state: {
    due_at: string
    state: 'new' | 'learning' | 'review' | 'relearning'
    reps: number
  }
}

export interface StudySessionNext {
  session: StudySession
  task: StudyTask | null
}

export interface ReviewAttemptPayload {
  session_id: number
  card_id: number
  card_revision: number
  client_attempt_id: string
  rating: number
  response_ms: number
  hint_used: boolean
  reveal_count: number
  answer_payload: Record<string, string | number | boolean | null>
  expected_due_at: string
  expected_state: string
  expected_reps: number
}

interface ErrorEnvelope {
  code?: string
  message?: string
  detail?: string
  request_id?: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface MobileApi {
  activate(activationCode: string, deviceLabel: string | null): Promise<SessionToken>
  refresh(accessToken: string): Promise<SessionToken>
  getMe(accessToken: string): Promise<Owner>
  logout(accessToken: string): Promise<void>
  getLearningProfile(accessToken: string): Promise<LearningProfile>
  updateLearningProfile(accessToken: string, payload: LearningProfileUpdate): Promise<LearningProfile>
  listSessions(accessToken: string): Promise<{ items: SessionDevice[] }>
  revokeSession(accessToken: string, sessionId: number): Promise<void>
  exportOwnerData(accessToken: string): Promise<OwnerDataExport>
  listBooks(accessToken: string): Promise<CatalogBook[]>
  listChapters(accessToken: string, bookId: number): Promise<CatalogChapter[]>
  searchCards(accessToken: string, params: { bookId?: number; chapterId?: number; query?: string; offset?: number; limit?: number }): Promise<CatalogCardPage>
  getCard(accessToken: string, cardId: number): Promise<CatalogCardDetail>
  enroll(accessToken: string, payload: { scope: 'card' | 'chapter' | 'book'; card_id?: number; chapter_id?: number; book_id?: number; priority?: number }): Promise<EnrollmentBatch>
  updateEnrollment(accessToken: string, enrollmentId: number, status: 'active' | 'suspended' | 'retired'): Promise<void>
  updateChapterEnrollments(accessToken: string, chapterId: number, status: 'active' | 'suspended'): Promise<ChapterEnrollmentResult>
  getInsightSummary(accessToken: string): Promise<InsightSummary>
  getInsightWorkload(accessToken: string): Promise<InsightWorkload>
  getWeakTopics(accessToken: string, offset?: number, limit?: number): Promise<WeakTopicPage>
  getToday(accessToken: string): Promise<DailyPlan>
  adjustTodayBudget(accessToken: string, minutes: number): Promise<DailyPlan>
  createStudySession(accessToken: string, dailyPlanId: number): Promise<StudySession>
  getNextTask(accessToken: string, sessionId: number): Promise<StudySessionNext>
  submitReviewAttempt(accessToken: string, payload: ReviewAttemptPayload): Promise<void>
  completeStudySession(accessToken: string, sessionId: number): Promise<StudySession>
  interruptStudySession(accessToken: string, sessionId: number): Promise<StudySession>
  resumeStudySession(accessToken: string, sessionId: number): Promise<StudySession>
}

interface ApiClientOptions {
  baseUrl: string
  fetch?: typeof fetch
}

export function createApiClient(options: ApiClientOptions): MobileApi {
  const fetchRequest = options.fetch ?? globalThis.fetch
  const apiBase = options.baseUrl.replace(/\/+$/, '') + '/api/v1'

  async function request<T>(
    path: string,
    init: RequestInit,
    accessToken?: string,
    timeoutMs = 15_000
  ): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (init.body) headers.set('Content-Type', 'application/json')
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

    let response: Response
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
    try {
      response = await fetchRequest(apiBase + path, { ...init, headers, signal: controller.signal })
    } catch {
      throw new ApiError(0, 'NETWORK_ERROR', '无法连接服务器，请检查网络后重试')
    } finally {
      window.clearTimeout(timeout)
    }
    if (!response.ok) throw await responseError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  return {
    activate(activationCode, deviceLabel) {
      return request<SessionToken>('/auth/mobile/activate', {
        method: 'POST',
        body: JSON.stringify({
          activation_code: activationCode,
          device_label: deviceLabel
        })
      })
    },
    refresh(accessToken) {
      return request<SessionToken>('/auth/refresh', { method: 'POST' }, accessToken)
    },
    getMe(accessToken) {
      return request<Owner>('/me', { method: 'GET' }, accessToken)
    },
    logout(accessToken) {
      return request<void>('/auth/logout', { method: 'POST' }, accessToken)
    },
    getLearningProfile(accessToken) {
      return request<LearningProfile>('/me/learning-profile', { method: 'GET' }, accessToken)
    },
    updateLearningProfile(accessToken, payload) {
      return request<LearningProfile>('/me/learning-profile', { method: 'PUT', body: JSON.stringify(payload) }, accessToken)
    },
    listSessions(accessToken) {
      return request<{ items: SessionDevice[] }>('/me/sessions', { method: 'GET' }, accessToken)
    },
    revokeSession(accessToken, sessionId) {
      return request<void>(`/me/sessions/${sessionId}`, { method: 'DELETE' }, accessToken)
    },
    exportOwnerData(accessToken) {
      return request<OwnerDataExport>('/me/export', { method: 'GET' }, accessToken)
    },
    listBooks(accessToken) {
      return request<CatalogBook[]>('/catalog/books', { method: 'GET' }, accessToken)
    },
    listChapters(accessToken, bookId) {
      return request<CatalogChapter[]>(`/catalog/books/${bookId}/chapters`, { method: 'GET' }, accessToken)
    },
    searchCards(accessToken, params) {
      const query = new URLSearchParams()
      if (params.bookId) query.set('book_id', String(params.bookId))
      if (params.chapterId) query.set('chapter_id', String(params.chapterId))
      if (params.query?.trim()) query.set('q', params.query.trim())
      query.set('offset', String(params.offset ?? 0))
      query.set('limit', String(params.limit ?? 20))
      return request<CatalogCardPage>(`/catalog/cards?${query}`, { method: 'GET' }, accessToken)
    },
    getCard(accessToken, cardId) {
      return request<CatalogCardDetail>(`/catalog/cards/${cardId}`, { method: 'GET' }, accessToken)
    },
    enroll(accessToken, payload) {
      return request<EnrollmentBatch>('/enrollments', { method: 'POST', body: JSON.stringify(payload) }, accessToken)
    },
    updateEnrollment(accessToken, enrollmentId, status) {
      return request<void>(`/enrollments/${enrollmentId}`, { method: 'PUT', body: JSON.stringify({ status }) }, accessToken)
    },
    updateChapterEnrollments(accessToken, chapterId, status) {
      return request<ChapterEnrollmentResult>(`/chapters/${chapterId}/enrollments`, { method: 'PUT', body: JSON.stringify({ status }) }, accessToken)
    },
    getInsightSummary(accessToken) {
      return request<InsightSummary>('/insights/summary', { method: 'GET' }, accessToken)
    },
    getInsightWorkload(accessToken) {
      return request<InsightWorkload>('/insights/workload', { method: 'GET' }, accessToken)
    },
    getWeakTopics(accessToken, offset = 0, limit = 20) {
      return request<WeakTopicPage>(`/insights/weak-topics?offset=${offset}&limit=${limit}`, { method: 'GET' }, accessToken)
    },
    getToday(accessToken) {
      return request<DailyPlan>('/learning/today', { method: 'GET' }, accessToken)
    },
    adjustTodayBudget(accessToken, minutes) {
      return request<DailyPlan>(
        '/learning/today',
        { method: 'PUT', body: JSON.stringify({ budget_minutes: minutes }) },
        accessToken
      )
    },
    createStudySession(accessToken, dailyPlanId) {
      return request<StudySession>(
        '/study-sessions',
        { method: 'POST', body: JSON.stringify({ daily_plan_id: dailyPlanId, auto_start: true }) },
        accessToken
      )
    },
    getNextTask(accessToken, sessionId) {
      return request<StudySessionNext>(
        `/study-sessions/${sessionId}/next`,
        { method: 'GET' },
        accessToken
      )
    },
    submitReviewAttempt(accessToken, payload) {
      return request<void>(
        '/review-attempts',
        { method: 'POST', body: JSON.stringify(payload) },
        accessToken
      )
    },
    completeStudySession(accessToken, sessionId) {
      return request<StudySession>(
        `/study-sessions/${sessionId}/complete`,
        { method: 'POST' },
        accessToken
      )
    },
    interruptStudySession(accessToken, sessionId) {
      return request<StudySession>(
        `/study-sessions/${sessionId}/interrupt`,
        { method: 'POST', body: JSON.stringify({ reason: '用户主动退出' }) },
        accessToken
      )
    },
    resumeStudySession(accessToken, sessionId) {
      return request<StudySession>(
        `/study-sessions/${sessionId}/resume`,
        { method: 'POST' },
        accessToken
      )
    }
  }
}

async function responseError(response: Response): Promise<ApiError> {
  let body: ErrorEnvelope = {}
  try {
    body = (await response.json()) as ErrorEnvelope
  } catch {
    // Non-JSON gateway errors still map to a stable client error.
  }
  return new ApiError(
    response.status,
    body.code ?? 'HTTP_ERROR',
    body.message ?? (response.status === 401 ? '设备会话已失效，请重新激活' : body.detail ?? '服务器暂时无法处理请求'),
    body.request_id
  )
}
