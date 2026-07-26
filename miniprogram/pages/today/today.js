'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')
const format = require('../../utils/format')

function reasonLabel(code) {
  return (
    {
      DUE: '今天到期',
      OVERDUE: '已有积压',
      REPAIR_REPEATED_AGAIN: '近期反复遗忘',
      REPAIR_TAG_CONFUSION: '相近概念易混',
      REPAIR_CARD_ISSUE: '卡片需要修复',
      WEAK_SLOW_HARD: '回忆耗时较长',
      NEW_FROM_PRIORITY_CHAPTER: '优先学科新内容',
      NEW_FROM_QUEUED: '已加入的新内容'
    }[code] || '按当前计划安排'
  )
}

const BUDGET_PRESETS = [10, 20, 30]

function budgetOptionsForPlan(plan) {
  // Merge the presets with the plan's own budgets so the owner's configured
  // daily_minutes (and any server-side adjustment) is always selectable.
  const values = BUDGET_PRESETS.concat([
    Number(plan && plan.budget_minutes) || 0,
    Number(plan && plan.effective_budget_minutes) || 0
  ])
  return values
    .filter(function (minutes, index) {
      return minutes >= 5 && minutes <= 240 && values.indexOf(minutes) === index
    })
    .sort(function (a, b) {
      return a - b
    })
}

Page({
  data: {
    viewState: 'loading',
    errorView: null,
    plan: null,
    preview: [],
    pendingCount: 0,
    budgetOptions: BUDGET_PRESETS,
    adjusting: false,
    starting: false,
    dateLabel: ''
  },

  onLoad: function () {
    this.guard = requests.createPageRequestGuard()
  },

  onShow: function () {
    this.onboardingOpen = false
    this.loadEntry()
  },

  onHide: function () {
    this.guard.invalidate()
  },

  onUnload: function () {
    this.guard.dispose()
  },

  loadEntry: function () {
    const self = this
    this.setData({ viewState: 'loading', errorView: null })
    return requests.loadWithAuth(this.guard, {
      authorized: function () {
        const snap = api.getAuthSnapshot()
        return Boolean(snap && snap.authState === 'ready')
      },
      onUnauthorized: function () {
        self.setData({
          viewState: 'unauthorized',
          errorView: { message: '登录后才能生成个人学习计划' }
        })
      },
      fetch: function (isCurrent) {
        return api.getLearningProfile().then(function (profile) {
          if (!profile || !isCurrent()) return null
          if (!api.isOnboardingComplete(profile)) {
            self.setData({ viewState: 'onboarding' })
            self.openOnboarding()
            return null
          }
          return api.learning().getToday()
        })
      },
      onReady: function (plan) {
        self.applyPlan(plan)
      },
      onError: function (view) {
        self.setData({
          viewState: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      },
      fallback: '今日计划加载失败，请重试'
    })
  },

  applyPlan: function (plan) {
    const items = (plan && plan.items) || []
    const pending = items.filter(function (item) {
      return item.status === 'pending'
    })
    const preview = pending.slice(0, 5).map(function (item, index) {
      return {
        id: item.id,
        index: index + 1,
        label: format.itemTypeLabel(item.item_type),
        minutes: Math.max(1, Math.ceil(item.estimated_seconds / 60)),
        reason: reasonLabel(item.reason_code)
      }
    })
    const state = !items.length
      ? 'empty'
      : !pending.length
        ? 'completed'
        : plan.new_cards_paused
          ? 'overloaded'
          : 'ready'
    this.setData({
      viewState: state,
      plan: plan,
      pendingCount: pending.length,
      preview: preview,
      budgetOptions: budgetOptionsForPlan(plan),
      dateLabel: format.localDateLabel(plan.plan_date),
      adjusting: false,
      starting: false
    })
  },

  onRetry: function () {
    this.loadEntry()
  },

  onAdjustBudget: function (event) {
    if (this.data.adjusting || this.data.starting || !this.data.plan) return
    const minutes = Number(event.currentTarget.dataset.minutes)
    if (!minutes || this.data.plan.effective_budget_minutes === minutes) return
    const sequence = this.guard.begin()
    const self = this
    this.setData({ adjusting: true })
    api
      .learning()
      .adjustTodayBudget(minutes)
      .then(function (plan) {
        if (self.guard.isCurrent(sequence)) self.applyPlan(plan)
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          adjusting: false,
          viewState: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      })
  },

  onStart: function () {
    if (this.data.starting || !this.data.plan || !this.data.pendingCount) return
    const sequence = this.guard.begin()
    const self = this
    this.setData({ starting: true })
    api
      .learning()
      .createStudySession(this.data.plan.id)
      .then(function (session) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ starting: false })
        wx.navigateTo({ url: '/pages/study-session/study-session?id=' + session.id })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          starting: false,
          viewState: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view
        })
      })
  },

  openOnboarding: function () {
    if (this.onboardingOpen) return
    this.onboardingOpen = true
    wx.navigateTo({
      url: '/pages/onboarding/onboarding',
      fail: function () {
        this.onboardingOpen = false
      }.bind(this)
    })
  },

  onOpenOnboarding: function () {
    this.openOnboarding()
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
