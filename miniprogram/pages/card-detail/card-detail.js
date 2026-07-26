'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')

const ENROLLMENT_LABELS = {
  queued: '已加入，等待计划引入',
  active: '学习中',
  suspended: '已暂停',
  retired: '已退出'
}

function decorateDetail(detail) {
  return Object.assign({}, detail, {
    enrollmentStatusLabel: detail.enrollment_status
      ? ENROLLMENT_LABELS[detail.enrollment_status] || detail.enrollment_status
      : '未加入',
    masteryLabel: detail.mastered ? '已达到' : detail.review_state ? '学习中' : '未开始',
    sources: (detail.sources || []).map(function (row) {
      return Object.assign({}, row, {
        chapter_label: (row.chapter_path || []).join(' / ')
      })
    })
  })
}

Page({
  data: {
    cardId: 0,
    state: 'loading',
    detail: null,
    errorView: null,
    inlineError: '',
    changing: false,
    sourceOpen: false
  },

  onLoad: function (options) {
    this.guard = requests.createPageRequestGuard()
    this.setData({ cardId: Number(options && options.id) })
    this.load()
  },

  onUnload: function () {
    this.guard.dispose()
  },

  load: function () {
    const sequence = this.guard.begin()
    const self = this
    this.setData({ state: 'loading', errorView: null, inlineError: '' })
    return api
      .catalog()
      .getCard(this.data.cardId)
      .then(function (detail) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ state: 'ready', detail: decorateDetail(detail), changing: false })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          state: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view,
          changing: false
        })
      })
  },

  onJoin: function () {
    if (this.data.changing) return
    const sequence = this.guard.begin()
    const self = this
    this.setData({ changing: true, inlineError: '' })
    api
      .learning()
      .enroll({ scope: 'card', card_id: this.data.cardId, priority: 50 })
      .then(function () {
        if (!self.guard.isCurrent(sequence)) return
        return self.load()
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ changing: false, inlineError: requests.errorView(error).message })
      })
  },

  onToggleStatus: function () {
    const detail = this.data.detail
    if (this.data.changing || !detail || !detail.enrollment_id) return
    const status = detail.enrollment_status === 'suspended' ? 'active' : 'suspended'
    const sequence = this.guard.begin()
    const self = this
    this.setData({ changing: true, inlineError: '' })
    api
      .learning()
      .updateEnrollment(detail.enrollment_id, status)
      .then(function () {
        if (!self.guard.isCurrent(sequence)) return
        return self.load()
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        self.setData({ changing: false, inlineError: requests.errorView(error).message })
      })
  },

  onOpenSource: function () {
    this.setData({ sourceOpen: true })
  },

  onCloseSource: function () {
    this.setData({ sourceOpen: false })
  },

  onRetry: function () {
    this.load()
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
