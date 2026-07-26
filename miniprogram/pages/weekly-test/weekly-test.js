'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')
const weekly = require('../../utils/weekly-test')

Page({
  data: {
    state: 'loading',
    errorView: null,
    mixedCount: 0,
    completedCount: 0,
    pendingBeforeCount: 0,
    plan: null,
    starting: false
  },

  onLoad: function () {
    this.guard = requests.createPageRequestGuard()
    this.load()
  },

  onUnload: function () {
    this.guard.dispose()
  },

  load: function () {
    const sequence = this.guard.begin()
    const self = this
    this.setData({ state: 'loading', errorView: null })
    return api
      .learning()
      .getToday()
      .then(function (plan) {
        if (!self.guard.isCurrent(sequence)) return
        const summary = weekly.summarizeWeeklyPlan(plan)
        self.setData({
          state: summary.state,
          mixedCount: summary.mixedPendingCount,
          completedCount: summary.mixedCompletedCount,
          pendingBeforeCount: summary.pendingBeforeCount,
          plan: plan,
          starting: false
        })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          state: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view,
          starting: false
        })
      })
  },

  onStart: function () {
    if (this.data.starting || this.data.state !== 'ready' || !this.data.plan) return
    const sequence = this.guard.begin()
    const self = this
    this.setData({ starting: true })
    api
      .learning()
      .createStudySession(this.data.plan.id)
      .then(function (session) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ starting: false })
        wx.redirectTo({ url: '/pages/study-session/study-session?id=' + session.id })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          starting: false,
          state: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      })
  },

  onOpenToday: function () {
    wx.switchTab({ url: '/pages/today/today' })
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  },

  onRetry: function () {
    this.load()
  }
})
