'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')
const repairDisplay = require('../../utils/repair-display')

Page({
  data: {
    state: 'loading',
    errorView: null,
    items: [],
    offset: 0,
    total: 0,
    hasMore: false,
    loadingMore: false,
    selectedSources: [],
    sourceOpen: false
  },

  onLoad: function (options) {
    this.guard = requests.createPageRequestGuard()
    this.targetId = Number(options && options.id) || 0
    this.load(false)
  },

  onUnload: function () {
    this.guard.dispose()
  },

  load: function (append) {
    if (append && this.data.loadingMore) return Promise.resolve()
    const sequence = this.guard.begin()
    const offset = append ? this.data.offset : 0
    const self = this
    this.setData({
      state: append ? this.data.state : 'loading',
      loadingMore: append,
      errorView: null
    })
    return api
      .insights()
      .getWeakTopics({ offset: offset, limit: 20 })
      .then(function (page) {
        if (!self.guard.isCurrent(sequence)) return
        const pageRows = page.items || []
        let rows = pageRows.map(repairDisplay.decorateRepairSuggestion)
        if (self.targetId) {
          rows = rows.filter(function (item) {
            return item.card_id === self.targetId
          })
        }
        const items = append ? self.data.items.concat(rows) : rows
        const nextOffset = offset + pageRows.length
        if (self.targetId && !items.length && page.has_more) {
          // The deep-linked card may rank past this page; keep searching.
          self.setData({ offset: nextOffset, loadingMore: false })
          self.load(true)
          return
        }
        self.setData({
          state: items.length ? 'ready' : 'empty',
          items: items,
          offset: nextOffset,
          total: page.total,
          hasMore: Boolean(page.has_more) && !self.targetId,
          loadingMore: false
        })
      })
      .catch(function (error) {
        if (!self.guard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          state: view.unauthorized ? 'unauthorized' : 'error',
          errorView: view,
          loadingMore: false
        })
      })
  },

  onMore: function () {
    if (this.data.hasMore && !this.data.loadingMore) this.load(true)
  },

  onSource: function (event) {
    const cardId = Number(event.currentTarget.dataset.id)
    const item = this.data.items.filter(function (row) {
      return row.card_id === cardId
    })[0]
    if (item) this.setData({ sourceOpen: true, selectedSources: [item.source] })
  },

  onClose: function () {
    this.setData({ sourceOpen: false, selectedSources: [] })
  },

  onRetry: function () {
    this.load(false)
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
