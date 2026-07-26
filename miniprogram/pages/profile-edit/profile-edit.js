const api = require('../../services/api')
const formHelpers = require('../../utils/profile-form')
const requests = require('../../utils/page-request')

Page({
  data: {
    loading: true,
    viewState: 'loading',
    errorView: null,
    saving: false,
    error: '',
    ok: '',
    showAdvanced: false,
    goalOptions: formHelpers.GOAL_OPTIONS,
    minutePresets: formHelpers.MINUTE_PRESETS,
    dayLabels: formHelpers.DAY_LABELS,
    form: formHelpers.defaultFormState()
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
    this.setData({
      loading: true,
      viewState: 'loading',
      errorView: null,
      error: '',
      ok: ''
    })
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
        self.setData({
          loading: false,
          viewState: 'ready',
          form: formHelpers.profileToForm(profile)
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

  patchForm: function (patch) {
    this.setData({
      form: Object.assign({}, this.data.form, patch),
      error: '',
      ok: ''
    })
  },

  onDisplayName: function (e) {
    this.patchForm({ display_name: e.detail.value })
  },

  onSelectGoal: function (e) {
    if (this.data.saving) return
    this.patchForm({ goal_type: e.currentTarget.dataset.value })
  },

  onTargetDate: function (e) {
    this.patchForm({ target_date: e.detail.value })
  },

  onClearDate: function () {
    if (this.data.saving) return
    this.patchForm({ target_date: '' })
  },

  onSelectMinutes: function (e) {
    if (this.data.saving) return
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
    if (this.data.saving) return
    const index = Number(e.currentTarget.dataset.index)
    const days = formHelpers.cloneStudyDays(this.data.form.study_days)
    days[index] = !days[index]
    this.patchForm({ study_days: days })
  },

  onToggleSubject: function (e) {
    if (this.data.saving) return
    const index = Number(e.currentTarget.dataset.index)
    const rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      return Object.assign({}, row, { enabled: !row.enabled })
    })
    this.patchForm({ subject_rows: rows })
  },

  onSubjectScore: function (e) {
    if (this.data.saving) return
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

  onToggleAdvanced: function () {
    this.setData({ showAdvanced: !this.data.showAdvanced })
  },

  onRetention: function (e) {
    this.patchForm({ desired_retention: e.detail.value })
  },

  onCeiling: function (e) {
    this.patchForm({ new_card_ceiling: e.detail.value })
  },

  onSave: function () {
    if (this.data.saving) return
    const sequence = this.guard.begin()
    this.setData({ saving: true, error: '', ok: '' })
    const self = this
    const options = { requireExamDate: false }
    // Keep onboarding completion state: if already complete, leave it;
    // if incomplete, saving from settings can also complete.
    if (!this.data.form.onboarding_completed) {
      options.completeOnboarding = true
    }

    api
      .saveLearningProfileForm(this.data.form, options)
      .then(function (profile) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({
          saving: false,
          ok: '档案已保存',
          form: formHelpers.profileToForm(profile)
        })
      })
      .catch(function (err) {
        if (!self.guard.isCurrent(sequence)) return
        let message = (err && err.message) || '保存失败'
        if (err && err.code === 'LEARNING_PROFILE_CONFLICT') {
          message = '档案已被其他设备更新，请刷新后重试'
        }
        self.setData({
          saving: false,
          error: message
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
