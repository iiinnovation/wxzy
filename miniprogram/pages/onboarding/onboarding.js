var api = require('../../services/api')
var formHelpers = require('../../utils/profile-form')

var TOTAL_STEPS = 5

Page({
  data: {
    loading: true,
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

  onShow: function () {
    this.loadProfile()
  },

  loadProfile: function () {
    var snap = api.getAuthSnapshot()
    if (!snap || (snap.authState !== 'ready' && !snap.hasSession && !snap.hasDevToken)) {
      this.setData({
        loading: false,
        error: '请先登录后再设置学习档案。'
      })
      return
    }

    this.setData({ loading: true, error: '', ok: '' })
    var self = this
    api
      .getLearningProfile()
      .then(function (profile) {
        var form = formHelpers.profileToForm(profile)
        self.setData({
          loading: false,
          form: form,
          summary: self.buildLiveSummary(form),
          progressPercent: self.calcProgress(self.data.step)
        })
      })
      .catch(function (err) {
        self.setData({
          loading: false,
          error: (err && err.message) || '档案加载失败'
        })
      })
  },

  calcProgress: function (step) {
    return Math.round((step / TOTAL_STEPS) * 100)
  },

  buildLiveSummary: function (form) {
    var maps = formHelpers.subjectMapsFromRows(form.subject_rows)
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
    var form = Object.assign({}, this.data.form, patch)
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
    var value = Number(e.currentTarget.dataset.value)
    this.patchForm({ daily_minutes: value, custom_minutes: '' })
  },

  onCustomMinutes: function (e) {
    var value = e.detail.value
    var n = Number(value)
    this.patchForm({
      custom_minutes: value,
      daily_minutes: Number.isFinite(n) && n > 0 ? n : this.data.form.daily_minutes
    })
  },

  onToggleDay: function (e) {
    var index = Number(e.currentTarget.dataset.index)
    var days = formHelpers.cloneStudyDays(this.data.form.study_days)
    days[index] = !days[index]
    this.patchForm({ study_days: days })
  },

  onToggleSubject: function (e) {
    var index = Number(e.currentTarget.dataset.index)
    var rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      return Object.assign({}, row, { enabled: !row.enabled })
    })
    this.patchForm({ subject_rows: rows })
  },

  onSubjectScore: function (e) {
    var index = Number(e.currentTarget.dataset.index)
    var field = e.currentTarget.dataset.field
    var value = formHelpers.clampScore(e.detail.value)
    var rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      var next = Object.assign({}, row)
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
    var step = this.data.step - 1
    this.setData({ step: step, progressPercent: this.calcProgress(step), error: '' })
  },

  onSkipOptional: function () {
    if (this.data.saving) return
    var step = this.data.step
    if (step === 2) {
      this.patchForm({ target_date: '', custom_minutes: '', daily_minutes: 20 })
    }
    if (step === 4) {
      var rows = this.data.form.subject_rows.map(function (row) {
        return Object.assign({}, row, { enabled: false })
      })
      this.patchForm({ subject_rows: rows })
    }
    if (step < TOTAL_STEPS) {
      var next = step + 1
      this.setData({ step: next, progressPercent: this.calcProgress(next), error: '' })
    }
  },

  onNext: function () {
    if (this.data.saving) return
    var step = this.data.step
    if (step < TOTAL_STEPS) {
      var validation = formHelpers.validateForm(this.data.form, {
        requireExamDate: false
      })
      if (step === 1 && !validation.ok && validation.errors[0] === '请选择学习目的') {
        this.setData({ error: validation.errors[0] })
        return
      }
      if (step === 2) {
        var minutes = formHelpers.resolveDailyMinutes(this.data.form)
        if (minutes == null || minutes < 5 || minutes > 240) {
          this.setData({ error: '每日分钟需在 5–240 之间' })
          return
        }
      }
      if (step === 3 && !this.data.form.study_days.some(Boolean)) {
        this.setData({ error: '请至少选择一个学习日' })
        return
      }
      var next = step + 1
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
    this.setData({ saving: true, error: '', ok: '' })
    var self = this
    api
      .saveLearningProfileForm(this.data.form, {
        completeOnboarding: true,
        requireExamDate: this.data.form.goal_type === 'exam'
      })
      .then(function (profile) {
        var form = formHelpers.profileToForm(profile)
        self.setData({
          saving: false,
          form: form,
          ok: '学习档案已保存',
          summary: formHelpers.summarizeProfile(profile)
        })
        setTimeout(function () {
          wx.switchTab({ url: '/pages/today/today' })
        }, 400)
      })
      .catch(function (err) {
        self.setData({
          saving: false,
          error: (err && err.message) || '保存失败'
        })
      })
  }
})
