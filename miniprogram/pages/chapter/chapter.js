'use strict'

const api = require('../../services/api')
const requests = require('../../utils/page-request')

function decodeName(value) {
  try {
    return decodeURIComponent(value || '')
  } catch (error) {
    return String(value || '')
  }
}

function decorateChapter(chapter) {
  const published = Number(chapter.published_card_count || 0)
  const enrolled = Number(chapter.enrolled_card_count || 0)
  const active = Number(chapter.active_card_count || 0)
  const suspended = Number(chapter.suspended_card_count || 0)
  let actionType = ''
  let actionLabel = ''

  if (published > enrolled) {
    actionType = 'join'
    actionLabel = '加入本章其余卡片'
  } else if (active > 0) {
    actionType = 'suspend'
    actionLabel = '暂停本章'
  } else if (suspended > 0) {
    actionType = 'resume'
    actionLabel = '恢复本章'
  } else if (enrolled > 0) {
    actionLabel = '等待计划引入'
  } else {
    actionLabel = '暂无可加入卡片'
  }

  return Object.assign({}, chapter, {
    actionType: actionType,
    actionLabel: actionLabel,
    actionDisabled: !actionType,
    enrollmentLabel: [
      '排队 ' + Number(chapter.queued_card_count || 0),
      '学习中 ' + active,
      '暂停 ' + suspended
    ].join(' · ')
  })
}

function decorateCard(card) {
  const pages = card.source_pages || []
  return Object.assign({}, card, {
    sourceLabel: pages.length ? 'PDF ' + pages[0] : '来源可查看'
  })
}

Page({
  data: {
    bookId: 0,
    bookName: '',
    state: 'loading',
    errorView: null,
    inlineError: '',
    chapters: [],
    activeChapter: null,
    cards: [],
    offset: 0,
    total: 0,
    hasMore: false,
    loadingMore: false,
    changing: false,
    keyword: ''
  },

  onLoad: function (options) {
    options = options || {}
    this.chapterGuard = requests.createPageRequestGuard()
    this.cardGuard = requests.createPageRequestGuard()
    this.actionGuard = requests.createPageRequestGuard()
    this.setData({
      bookId: Number(options.bookId),
      bookName: decodeName(options.name)
    })
    this.loadChapters()
  },

  onUnload: function () {
    this.chapterGuard.dispose()
    this.cardGuard.dispose()
    this.actionGuard.dispose()
  },

  onPullDownRefresh: function () {
    this.loadChapters().then(function () {
      wx.stopPullDownRefresh()
    })
  },

  loadChapters: function () {
    const sequence = this.chapterGuard.begin()
    const selectedId = this.data.activeChapter && this.data.activeChapter.id
    const self = this
    this.setData({ state: 'loading', errorView: null })
    return api
      .catalog()
      .listChapters(this.data.bookId)
      .then(function (rows) {
        if (!self.chapterGuard.isCurrent(sequence)) return
        const chapters = (rows || []).map(decorateChapter)
        if (!chapters.length) {
          self.cardGuard.invalidate()
          self.setData({
            state: 'empty',
            chapters: [],
            activeChapter: null,
            cards: []
          })
          return
        }
        const selected = chapters.filter(function (chapter) {
          return chapter.id === selectedId
        })[0] || chapters[0]
        self.setData({ state: 'ready', chapters: chapters })
        self.selectChapter(selected)
      })
      .catch(function (error) {
        if (!self.chapterGuard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({ state: view.unauthorized ? 'unauthorized' : 'error', errorView: view })
      })
  },

  selectChapter: function (chapter) {
    this.setData({
      activeChapter: chapter,
      cards: [],
      offset: 0,
      total: 0,
      hasMore: false,
      inlineError: ''
    })
    this.loadCards(false)
  },

  onSelectChapter: function (event) {
    const id = Number(event.currentTarget.dataset.id)
    const chapter = this.data.chapters.filter(function (row) {
      return row.id === id
    })[0]
    if (chapter && (!this.data.activeChapter || chapter.id !== this.data.activeChapter.id)) {
      this.selectChapter(chapter)
    }
  },

  loadCards: function (append) {
    if (!this.data.activeChapter) return Promise.resolve()
    const sequence = this.cardGuard.begin()
    const chapterId = this.data.activeChapter.id
    const offset = append ? this.data.offset : 0
    const self = this
    this.setData({ loadingMore: true, inlineError: '' })
    return api
      .catalog()
      .searchCards({
        book_id: this.data.bookId,
        chapter_id: chapterId,
        q: this.data.keyword,
        offset: offset,
        limit: 20
      })
      .then(function (page) {
        if (!self.cardGuard.isCurrent(sequence)) return
        const next = (page.items || []).map(decorateCard)
        self.setData({
          cards: append ? self.data.cards.concat(next) : next,
          offset: offset + next.length,
          total: Number(page.total || 0),
          hasMore: Boolean(page.has_more),
          loadingMore: false
        })
      })
      .catch(function (error) {
        if (!self.cardGuard.isCurrent(sequence)) return
        const view = requests.errorView(error)
        self.setData({
          loadingMore: false,
          inlineError: view.message
        })
      })
  },

  onLoadMore: function () {
    if (this.data.hasMore && !this.data.loadingMore) this.loadCards(true)
  },

  onKeyword: function (event) {
    this.setData({ keyword: event.detail.value })
  },

  onSearch: function () {
    if (!this.data.loadingMore) this.loadCards(false)
  },

  onChapterAction: function () {
    const chapter = this.data.activeChapter
    if (this.data.changing || !chapter || chapter.actionDisabled) return
    if (chapter.actionType === 'join') {
      this.joinChapter(chapter.id)
      return
    }
    this.changeChapterStatus(chapter.id, chapter.actionType === 'suspend' ? 'suspended' : 'active')
  },

  joinChapter: function (chapterId) {
    const sequence = this.actionGuard.begin()
    const self = this
    this.setData({ changing: true, inlineError: '' })
    api
      .learning()
      .enroll({ scope: 'chapter', chapter_id: chapterId, priority: 60 })
      .then(function (result) {
        if (!self.actionGuard.isCurrent(sequence)) return
        wx.showToast({
          title: result.created_count ? '已加入 ' + result.created_count + ' 张' : '本章已加入',
          icon: 'none'
        })
        self.setData({ changing: false })
        return self.loadChapters()
      })
      .catch(function (error) {
        if (!self.actionGuard.isCurrent(sequence)) return
        self.setData({
          changing: false,
          inlineError: requests.errorView(error).message
        })
      })
  },

  changeChapterStatus: function (chapterId, status) {
    const sequence = this.actionGuard.begin()
    const self = this
    this.setData({ changing: true, inlineError: '' })
    api
      .learning()
      .updateChapterEnrollments(chapterId, status)
      .then(function (result) {
        if (!self.actionGuard.isCurrent(sequence)) return
        wx.showToast({
          title: status === 'suspended' ? '已暂停 ' + result.updated_count + ' 张' : '已恢复 ' + result.updated_count + ' 张',
          icon: 'none'
        })
        self.setData({ changing: false })
        return self.loadChapters()
      })
      .catch(function (error) {
        if (!self.actionGuard.isCurrent(sequence)) return
        self.setData({
          changing: false,
          inlineError: requests.errorView(error).message
        })
      })
  },

  onOpenCard: function (event) {
    wx.navigateTo({ url: '/pages/card-detail/card-detail?id=' + event.currentTarget.dataset.id })
  },

  onRetry: function () {
    this.loadChapters()
  },

  onLogin: function () {
    wx.switchTab({ url: '/pages/me/me' })
  }
})
