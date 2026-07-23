var api = require('../../services/api')
var formHelpers = require('../../utils/profile-form')

Page({
  data: {
    loading: true,
    saving: false,
    error: '',
    ok: '',
    showAdvanced: false,
    goalOptions: formHelpers.GOAL_OPTIONS,
    minutePresets: formHelpers.MINUTE_PRESETS,
    dayLabels: formHelpers.DAY_LABELS,
    form: formHelpers.defaultFormState()
  },

  onShow: function () {
    this.loadProfile()
  },

  loadProfile: function () {
    var snap = api.getAuthSnapshot()
    if (!snap || (snap.authState !== 'ready' && !snap.hasSession && !snap.hasDevToken)) {
      this.setData({
        loading: false,
        error: '请先登录后再编辑学习档案。'
      })
      return
    }

    this.setData({ loading: true, error: '', ok: '' })
    var self = this
    api
      .getLearningProfile()
      .then(function (profile) {
        self.setData({
          loading: false,
          form: formHelpers.profileToForm(profile)
        })
      })
      .catch(function (err) {
        self.setData({
          loading: false,
          error: (err && err.message) || '档案加载失败'
        })
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
    if (this.data.saving) return
    var index = Number(e.currentTarget.dataset.index)
    var days = formHelpers.cloneStudyDays(this.data.form.study_days)
    days[index] = !days[index]
    this.patchForm({ study_days: days })
  },

  onToggleSubject: function (e) {
    if (this.data.saving) return
    var index = Number(e.currentTarget.dataset.index)
    var rows = this.data.form.subject_rows.map(function (row, i) {
      if (i !== index) return row
      return Object.assign({}, row, { enabled: !row.enabled })
    })
    this.patchForm({ subject_rows: rows })
  },

  onSubjectScore: function (e) {
    if (this.data.saving) return
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
    this.setData({ saving: true, error: '', ok: '' })
    var self = this
    var options = {
      requireExamDate: this.data.form.goal_type === 'exam'
    }
    // Keep onboarding completion state: if already complete, leave it;
    // if incomplete, saving from settings can also complete.
    if (!this.data.form.onboarding_completed) {
      options.completeOnboarding = true
    }

    api
      .saveLearningProfileForm(this.data.form, options)
      .then(function (profile) {
        self.setData({
          saving: false,
          ok: '档案已保存',
          form: formHelpers.profileToForm(profile)
        })
      })
      .catch(function (err) {
        var message = (err && err.message) || '保存失败'
        if (err && err.code === 'LEARNING_PROFILE_CONFLICT') {
          message = '档案已被其他设备更新，请刷新后重试'
        }
        self.setData({
          saving: false,
          error: message
        })
      })
  }
})
