const api = require('../../services/api')

Page({
  data: {
    loading: false,
    error: '',
    dueCount: 0,
    stats: {},
    preview: [],
    needsSetup: false
  },

  onShow() {
    this.loadData()
  },

  async loadData() {
    this.setData({ loading: true, error: '' })
    const snap = api.getAuthSnapshot ? api.getAuthSnapshot() : null
    const config = api.getConfig()
    if (!config.token && !(snap && snap.authState === 'ready')) {
      this.setData({
        loading: false,
        needsSetup: true,
        error: '尚未登录，请先在“我的”完成登录或开发连接设置。'
      })
      return
    }
    try {
      if (api.getLearningProfile) {
        try {
          const profile = await api.getLearningProfile()
          if (profile && !api.isOnboardingComplete(profile)) {
            this.setData({
              loading: false,
              needsSetup: true,
              error: '尚未完成学习档案设置，可先完成引导再开始今日计划。'
            })
            return
          }
        } catch (profileErr) {
          // If profile cannot load, continue with stats; auth errors handled below.
        }
      }
      const [stats, due] = await Promise.all([api.getStats(), api.getDue(5)])
      const preview = (due || []).map((item, index) => ({
        id: item.card.id,
        order: index + 1,
        question: item.card.question,
        book_name: item.card.book_name,
        section: item.card.section,
        chapter: item.card.chapter
      }))
      this.setData({
        stats: stats || {},
        dueCount: (stats && stats.due_now) || (due ? due.length : 0),
        preview,
        needsSetup: false,
        loading: false
      })
    } catch (e) {
      const message = e.message || '加载失败'
      this.setData({
        loading: false,
        needsSetup: message.indexOf('凭证') >= 0,
        error: message
      })
    }
  },

  onRefresh() {
    this.loadData()
  },

  onStartReview() {
    if (this.data.dueCount <= 0) return
    wx.navigateTo({ url: '/pages/review/review' })
  },

  onOpenSettings() {
    const message = this.data.error || ''
    if (message.indexOf('学习档案') >= 0) {
      wx.navigateTo({ url: '/pages/onboarding/onboarding' })
      return
    }
    wx.switchTab({ url: '/pages/me/me' })
  }
})
