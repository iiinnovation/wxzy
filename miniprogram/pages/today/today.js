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
    const config = api.getConfig()
    if (!config.token) {
      this.setData({
        loading: false,
        needsSetup: true,
        error: '尚未配置服务连接，请先完成连接设置。'
      })
      return
    }
    try {
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
    wx.switchTab({ url: '/pages/me/me' })
  }
})
