'use strict'

const api = require('../../services/api')
const requestUtils = require('../../utils/page-request')
const format = require('../../utils/format')
const quickReview = require('../../utils/quick-review')

Page({
  data: {
    sessionId: 0, session: null, task: null, viewState: 'loading', errorView: null,
    revealed: false, writtenAnswer: '', submitting: false, submitError: '', retryRating: 0,
    submitNeedsReload: false,
    recallMode: 'quick', writingExpanded: false, answerPointChecks: [],
    pointCheckTouched: false, recalledPointCount: 0, recommendedRating: 0,
    attemptId: '', completed: 0, total: 0, taskLabel: '学习任务',
    sourceOpen: false, sourceLoading: false, sourceError: '', sources: [], exiting: false, resuming: false,
    retryMode: 'load', exitError: ''
  },
  onLoad: function (options) {
    this.guard = requestUtils.createPageRequestGuard()
    this.sourceGuard = requestUtils.createPageRequestGuard()
    this.taskStartedAt = Date.now()
    const id = Number(options && options.id)
    this.setData({ sessionId: id })
    if (!id) {
      this.setData({ viewState: 'error', errorView: { message: '学习会话参数无效' } })
      return
    }
    this.loadNext()
  },
  onShow: function () {
    if (
      this.guard &&
      this.data.viewState === 'unauthorized' &&
      api.getAuthSnapshot().authState === 'ready'
    ) {
      this.loadNext()
    }
  },
  onUnload: function () {
    this.pageUnloaded = true
    this.guard.dispose()
    this.sourceGuard.dispose()
    if (this.data.submitting) {
      this.interruptAfterSubmit = true
      return
    }
    this.interruptActiveSession('页面离开')
  },
  interruptActiveSession: function (reason) {
    const session = this.data.session
    if (
      !this.data.sessionId ||
      this.data.exiting ||
      !session ||
      session.status !== 'active'
    ) return
    api.learning().interruptSession(this.data.sessionId, reason).catch(function () {
      // Page teardown cannot present recovery UI; the server remains authoritative.
    })
  },
  loadNext: function () {
    const sequence = this.guard.begin(), self = this
    this.setData({
      viewState: 'loading', errorView: null, submitError: '', retryMode: 'load'
    })
    api.learning().getNextTask(this.data.sessionId).then(function (result) {
      if (!self.guard.isCurrent(sequence)) return
      self.applyResult(result)
    }).catch(function (error) {
      if (!self.guard.isCurrent(sequence)) return
      const view = requestUtils.errorView(error, '下一项学习任务加载失败')
      self.setData({ viewState: view.unauthorized ? 'unauthorized' : 'error', errorView: view })
    })
  },
  applyResult: function (result) {
    this.sourceGuard.invalidate()
    this.pendingAttemptPayload = null
    const session = result.session || {}, task = result.task
    if (session.status === 'interrupted') {
      this.setData({ session: session, viewState: 'interrupted', completed: session.completed_task_count, total: session.planned_task_count })
      return
    }
    if (!task) {
      this.finishSession(session)
      return
    }
    this.taskStartedAt = Date.now()
    this.recallElapsedMs = null
    this.setData({
      session: session, task: task, viewState: 'recall', revealed: false, writtenAnswer: '',
      submitting: false, submitError: '', retryRating: 0, submitNeedsReload: false,
      recallMode: 'quick', writingExpanded: false,
      answerPointChecks: quickReview.decorateAnswerPoints(task.card.answer_points),
      pointCheckTouched: false, recalledPointCount: 0, recommendedRating: 0,
      attemptId: api.learning().createClientAttemptId(session.id, task.card.id),
      completed: session.completed_task_count, total: session.planned_task_count,
      taskLabel: format.itemTypeLabel(task.plan_item.item_type), sources: [], sourceOpen: false,
      sourceError: ''
    })
  },
  finishSession: function (session) {
    const self = this
    if (session.status === 'completed') {
      this.setData({ session: session, viewState: 'completed', completed: session.completed_task_count, total: session.planned_task_count })
      return
    }
    const sequence = this.guard.begin()
    api.learning().completeSession(this.data.sessionId).then(function (value) {
      if (!self.guard.isCurrent(sequence)) return
      self.setData({ session: value, viewState: 'completed', completed: value.completed_task_count, total: value.planned_task_count })
    }).catch(function (error) {
      if (!self.guard.isCurrent(sequence)) return
      self.setData({ viewState: 'error', errorView: requestUtils.errorView(error, '会话完成状态保存失败') })
    })
  },
  onSelectRecallMode: function (event) {
    if (this.data.revealed) return
    const mode = event.currentTarget.dataset.mode === 'writing' ? 'writing' : 'quick'
    this.setData({ recallMode: mode, writingExpanded: mode === 'writing' })
  },
  onWrittenInput: function (event) { this.setData({ writtenAnswer: event.detail.value }) },
  onReveal: function () {
    if (!this.data.task) return
    this.recallElapsedMs = Math.max(0, Date.now() - this.taskStartedAt)
    this.setData({ revealed: true, viewState: 'answer' })
  },
  onAnswerPointsChange: function (event) {
    if (this.data.submitting || this.data.retryRating) return
    const checks = quickReview.setCheckedAnswerPoints(
      this.data.answerPointChecks,
      event.detail.value
    )
    const recalled = quickReview.countRecalledPoints(checks)
    this.setData({
      answerPointChecks: checks,
      pointCheckTouched: true,
      recalledPointCount: recalled,
      recommendedRating: quickReview.recommendRating(checks, true, this.recallElapsedMs)
    })
  },
  onRecallNone: function () {
    if (this.data.submitting || this.data.retryRating) return
    const checks = quickReview.setCheckedAnswerPoints(this.data.answerPointChecks, [])
    this.setData({
      answerPointChecks: checks,
      pointCheckTouched: true,
      recalledPointCount: 0,
      recommendedRating: quickReview.recommendRating(checks, true, this.recallElapsedMs)
    })
  },
  onRate: function (event) {
    if (this.data.retryRating) return
    this.submitRating(Number(event.detail.rating), false)
  },
  submitRating: function (rating, isRetry) {
    if (
      this.data.submitting ||
      !this.data.task ||
      !rating ||
      (this.data.retryRating && !isRetry)
    ) return
    const sequence = this.guard.begin()
    this.setData({
      submitting: true,
      submitError: '',
      retryRating: rating,
      submitNeedsReload: false
    })
    let payload = this.pendingAttemptPayload
    if (!payload) {
      const task = this.data.task
      const state = task.review_state || {}
      payload = {
        session_id: this.data.sessionId, card_id: task.card.id, card_revision: task.card_revision,
        client_attempt_id: this.data.attemptId, rating: rating,
        response_ms: Math.max(0, Date.now() - this.taskStartedAt), hint_used: false,
        reveal_count: 1, expected_due_at: state.due_at, expected_state: state.state, expected_reps: state.reps
      }
      payload.answer_payload = quickReview.buildAnswerPayload({
        recallMode: this.data.recallMode,
        recallMs: this.recallElapsedMs,
        writtenAnswer: this.data.writtenAnswer,
        points: this.data.answerPointChecks,
        pointCheckTouched: this.data.pointCheckTouched
      })
      this.pendingAttemptPayload = payload
    }
    const self = this
    api.learning().submitReviewAttempt(payload, { timeout: 15000 }).then(function () {
      self.pendingAttemptPayload = null
      if (self.interruptAfterSubmit) {
        self.interruptAfterSubmit = false
        self.interruptActiveSession('评分完成后页面离开')
        return
      }
      if (!self.guard.isCurrent(sequence)) return
      self.setData({ submitting: false, retryRating: 0 })
      self.loadNext()
    }).catch(function (error) {
      if (self.interruptAfterSubmit) {
        // The page was left while this submit was in flight; still release the
        // session so it does not stay active and inflate actual minutes.
        self.interruptAfterSubmit = false
        self.interruptActiveSession('评分失败后页面离开')
        return
      }
      if (!self.guard.isCurrent(sequence)) return
      const canRetry = requestUtils.canRetrySameWrite(error)
      self.setData({
        submitting: false,
        submitError: error.message || '评分保存失败，请重试',
        submitNeedsReload: !canRetry
      })
    })
  },
  onRetrySubmit: function () {
    if (this.data.submitNeedsReload) return
    this.submitRating(this.data.retryRating, true)
  },
  onReloadAfterSubmitError: function () {
    this.pendingAttemptPayload = null
    this.setData({ submitError: '', retryRating: 0, submitNeedsReload: false })
    this.loadNext()
  },
  onRetryLoad: function () {
    if (this.data.retryMode === 'resume') {
      this.onResume()
      return
    }
    this.loadNext()
  },
  onResume: function () {
    if (this.data.resuming) return
    const sequence = this.guard.begin()
    const self = this
    this.setData({ resuming: true, viewState: 'loading', retryMode: 'resume' })
    api.learning().resumeSession(this.data.sessionId).then(function () {
      if (!self.guard.isCurrent(sequence)) return
      self.setData({ resuming: false })
      self.loadNext()
    }).catch(function (e) {
      if (!self.guard.isCurrent(sequence)) return
      self.setData({
        resuming: false,
        viewState: 'error',
        retryMode: 'resume',
        errorView: requestUtils.errorView(e)
      })
    })
  },
  onExit: function () {
    if (this.data.exiting || this.data.submitting) return
    const self = this
    wx.showModal({ title: '暂时结束学习？', content: '当前进度会保留，下次可从同一项继续。', confirmText: '保存退出', success: function (result) {
      if (!result.confirm) return
      const sequence = self.guard.begin()
      self.setData({ exiting: true, exitError: '' })
      api.learning().interruptSession(self.data.sessionId, '用户主动退出').then(function () {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ exiting: false })
        wx.navigateBack()
      }).catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({
          exiting: false,
          exitError: (error && error.message) || '暂停状态保存失败，请重试'
        })
      })
    } })
  },
  onOpenSource: function () {
    if (!this.data.task) return
    const sequence = this.sourceGuard.begin()
    const fallback = this.data.task.card.source_excerpt
      ? [{ id: 'fallback', book_name: this.data.task.card.book_name, excerpt: this.data.task.card.source_excerpt, pdf_page_start: (this.data.task.card.source_pages || [])[0] }]
      : []
    this.setData({ sourceOpen: true, sourceLoading: true, sourceError: '', sources: fallback })
    const self = this
    api.catalog().listCardSources(this.data.task.card.id).then(function (rows) {
      if (!self.sourceGuard.isCurrent(sequence)) return
      const sources = (rows || []).map(function (row) { return Object.assign({}, row, { chapter_label: (row.chapter_path || []).join(' / ') }) })
      self.setData({ sourceLoading: false, sourceError: '', sources: sources.length ? sources : fallback })
    }).catch(function (error) {
      if (self.sourceGuard.isCurrent(sequence)) {
        self.setData({
          sourceLoading: false,
          sourceError: (error && error.message) || '来源加载失败，请重试',
          sources: fallback
        })
      }
    })
  },
  onCloseSource: function () {
    this.sourceGuard.invalidate()
    this.setData({ sourceOpen: false, sourceLoading: false, sourceError: '' })
  },
  onBackToday: function () { wx.switchTab({ url: '/pages/today/today' }) },
  onLogin: function () { wx.switchTab({ url: '/pages/me/me' }) }
})
