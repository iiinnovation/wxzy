const api = require('../../services/api')
const formHelpers = require('../../utils/profile-form')
const requests = require('../../utils/page-request')

const TOTAL_STEPS = 5

Page({
  data: {
    loading: true,
    viewState: 'loading',
    errorView: null,
    saving: false,
    error: '',
    ok: '',
    step: 1,
    totalSteps: TOTAL_STEPS,
    progressPercent: 20,
    goalOptions: formHelpers.GOAL_OPTIONS,
    minutePresets: formHelpers.MINUTE_PRESETS,
    dayLabels: formHelpers.DAY_LABELS,
    form: formHelpers.defaultFormState(),
    summary: formHelpers.summarizeProfile(null)
  },

  onLoad: function () {
    this.guard = requests.createPageRequestGuard()
  },

  onShow: function () {
    this.loadProfile()
  },

  onUnload: function () {
    this.guard.dispose()
  },

  loadProfile: function () {
    const self = this
    this.setData({ loading: true, viewState: 'loading', errorView: null, error: '', ok: '' })
    return requests.loadWithAuth(this.guard, {
      authorized: function () {
        const snap = api.getAuthSnapshot()
        return Boolean(snap && (snap.authState === 'ready' || snap.hasSession || snap.hasDevToken))
      },
      onUnauthorized: function () {
        self.setData({ loading: false, viewState: 'unauthorized' })
      },
      fetch: function () {
        return api.getLearningProfile()
      },
      onReady: function (profile) {
        const form = formHelpers.profileToForm(profile)
        self.setData({
          loading: false,
          viewState: 'ready',
          form: form,
          summary: self.buildLiveSummary(form),
          progressPercent: self.calcProgress(self.data.step)
        })
      },
      onError: function (view) {
        self.setData({
          loading: false,
          viewState: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      },
      fallback: '档案加载失败，请重试'
    })
  },

  calcProgress: function (step) {
    return Math.round((step / TOTAL_STEPS) * 100)
  },

  buildLiveSummary: function (form) {
    const maps = formHelpers.subjectMapsFromRows(form.subject_rows)
    return formHelpers.summarizeProfile({
      goal_type: form.goal_type,
      daily_minutes: formHelpers.resolveDailyMinutes(form) || form.daily_minutes,
      study_days: form.study_days,
      target_date: form.target_date || null,
      subject_priorities: maps.subject_priorities,
      onboarding_completed_at: form.onboarding_completed ? 'x' : null,
      display_name: form.display_name
    })
  },

  patchForm: function (patch) {
    const form = Object.assign({}, this.data.form, patch)
    this.setData({
      form: form,
      summary: this.buildLiveSummary(form),
      error: ''
    })
  },

  onSelectGoal: function (e) {
    this.patchForm({ goal_type: e.currentTarget.dataset.value })
  },

  onTargetDate: function (e) {
    this.patchForm({ target_date: e.detail.value })
  },

  onClearDate: function () {
    this.patchForm({ target_date: '' })
  },

  onSelectMinutes: function (e) {
    const value = Number(e.currentTarget.dataset.value)
    this.patchForm({ daily_minutes: value, custom_minutes: '' })
  },

  onCustomMinutes: function (e) {
    const value = e.detail.value
    const n = Number(value)
    this.patchForm({
      custom_minutes: value,
      daily_minutes: Number.isFinite(n) && n > 0 ? n : this.data.form.daily_minutes
    })
  },

  onToggleDay: function (e) {
    const index = Number(e.currentTarget.dataset.index)
    const days = formHelpers.cloneStudyDays(this.data.form.study_days)
    days[index] = !days[index]
    this.patchForm({ study_days: days })
  },

  onToggleSubject: function (e) {
    const index = Number(e.currentTarget.dataset.index)
    const rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      return Object.assign({}, row, { enabled: !row.enabled })
    })
    this.patchForm({ subject_rows: rows })
  },

  onSubjectScore: function (e) {
    const index = Number(e.currentTarget.dataset.index)
    const field = e.currentTarget.dataset.field
    const value = formHelpers.clampScore(e.detail.value)
    const rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      const next = Object.assign({}, row)
      next[field] = value
      return next
    })
    this.patchForm({ subject_rows: rows })
  },

  onDisplayName: function (e) {
    this.patchForm({ display_name: e.detail.value })
  },

  onBack: function () {
    if (this.data.step <= 1 || this.data.saving) return
    const step = this.data.step - 1
    this.setData({ step: step, progressPercent: this.calcProgress(step), error: '' })
  },

  onSkipOptional: function () {
    if (this.data.saving) return
    const step = this.data.step
    if (step === 2) {
      this.patchForm({ target_date: '', custom_minutes: '', daily_minutes: 20 })
    }
    if (step === 4) {
      const rows = this.data.form.subject_rows.map(function (row) {
        return Object.assign({}, row, { enabled: false })
      })
      this.patchForm({ subject_rows: rows })
    }
    if (step < TOTAL_STEPS) {
      const next = step + 1
      this.setData({ step: next, progressPercent: this.calcProgress(next), error: '' })
    }
  },

  onNext: function () {
    if (this.data.saving) return
    const step = this.data.step
    if (step < TOTAL_STEPS) {
      const validation = formHelpers.validateForm(this.data.form, {
        requireExamDate: false
      })
      if (step === 1 && !validation.ok && validation.errors[0] === '请选择学习目的') {
        this.setData({ error: validation.errors[0] })
        return
      }
      if (step === 2) {
        const minutes = formHelpers.resolveDailyMinutes(this.data.form)
        if (minutes == null || minutes < 5 || minutes > 240) {
          this.setData({ error: '每日分钟需在 5–240 之间' })
          return
        }
      }
      if (step === 3 && !this.data.form.study_days.some(Boolean)) {
        this.setData({ error: '请至少选择一个学习日' })
        return
      }
      const next = step + 1
      this.setData({
        step: next,
        progressPercent: this.calcProgress(next),
        error: '',
        summary: this.buildLiveSummary(this.data.form)
      })
      return
    }
    this.submit()
  },

  submit: function () {
    if (this.data.saving) return
    const sequence = this.guard.begin()
    this.setData({ saving: true, error: '', ok: '' })
    const self = this
    api
      .saveLearningProfileForm(this.data.form, {
        completeOnboarding: true,
        requireExamDate: false
      })
      .then(function (profile) {
        if (!self.guard.isCurrent(sequence)) return
        const form = formHelpers.profileToForm(profile)
        self.setData({
          saving: false,
          viewState: 'completed',
          form: form,
          ok: '学习档案已保存',
          summary: formHelpers.summarizeProfile(profile)
        })
        setTimeout(function () {
          if (self.guard.isCurrent(sequence)) {
            wx.switchTab({ url: '/pages/today/today' })
          }
        }, 400)
      })
      .catch(function (err) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({
          saving: false,
          error: (err && err.message) || '保存失败'
        })
      })
  },

  onRetry: function () {
    this.loadProfile()
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
