'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')
const format = require('../../utils/format')
const repairDisplay = require('../../utils/repair-display')

const TREND_LABELS = {
  insufficient: '数据还不够',
  improving: '正在改善',
  declining: '需要关注',
  stable: '保持稳定'
}

Page({
  data: {
    state: 'loading',
    errorView: null,
    summary: null,
    workload: null,
    weak: [],
    workloadDays: []
  },

  onLoad: function () {
    this.guard = requests.createPageRequestGuard()
  },

  onShow: function () {
    this.load()
  },

  onHide: function () {
    this.guard.invalidate()
  },

  onUnload: function () {
    this.guard.dispose()
  },

  load: function () {
    const sequence = this.guard.begin()
    const self = this
    this.setData({ state: 'loading', errorView: null })
    return Promise.all([
      api.insights().getSummary(),
      api.insights().getWorkload(),
      api.insights().getWeakTopics({ offset: 0, limit: 5 })
    ])
      .then(function (values) {
        if (!self.guard.isCurrent(sequence)) return
        const summary = values[0]
        const workload = values[1]
        const weak = values[2]
        let maximum = 1
        ;(workload.days || []).forEach(function (day) {
          maximum = Math.max(maximum, day.estimated_minutes, day.budget_minutes)
        })
        const days = (workload.days || []).map(function (day) {
          return Object.assign({}, day, {
            label: format.localDateLabel(day.local_date),
            width: day.estimated_minutes
              ? Math.max(2, Math.round((day.estimated_minutes / maximum) * 100))
              : 0,
            status_label: day.overloaded ? '超出预算' : day.due_count ? '预算内' : '无到期'
          })
        })
        summary.subjects = (summary.subjects || []).map(function (subject) {
          return Object.assign({}, subject, {
            trend_label: TREND_LABELS[subject.trend] || TREND_LABELS.stable
          })
        })
        self.setData({
          state: 'ready',
          summary: summary,
          workload: workload,
          weak: (weak.items || []).map(repairDisplay.decorateRepairSuggestion),
          workloadDays: days
        })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          state: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      })
  },

  onRetry: function () {
    this.load()
  },

  onOpenWeak: function (event) {
    wx.navigateTo({ url: '/pages/weak-topic/weak-topic?id=' + event.currentTarget.dataset.id })
  },

  onOpenAllWeak: function () {
    wx.navigateTo({ url: '/pages/weak-topic/weak-topic' })
  },

  onOpenWeekly: function () {
    wx.navigateTo({ url: '/pages/weekly-test/weekly-test' })
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
