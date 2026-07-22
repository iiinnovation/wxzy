const api = require('../../services/api')

Page({
  data: {
    loading: false,
    error: '',
    queue: [],
    index: 0,
    current: null,
    showAnswer: false,
    submitting: false,
    done: false,
    lastSchedule: ''
  },

  onLoad() {
    this.loadQueue()
  },

  async loadQueue() {
    this.setData({ loading: true, error: '', done: false })
    try {
      const due = await api.getDue(30)
      const queue = due || []
      this.setData({
        queue,
        index: 0,
        current: queue[0] || null,
        showAnswer: false,
        loading: false,
        done: queue.length === 0
      })
    } catch (e) {
      this.setData({ loading: false, error: e.message || '加载失败' })
    }
  },

  onReveal() {
    this.setData({ showAnswer: true })
  },

  async onRate(e) {
    if (this.data.submitting || !this.data.current) return
    const rating = Number(e.currentTarget.dataset.rating)
    const cardId = this.data.current.card.id
    this.setData({ submitting: true, error: '' })
    try {
      const res = await api.postAnswer(cardId, rating)
      const days = res && res.scheduled_days != null ? Number(res.scheduled_days).toFixed(2) : ''
      const nextIndex = this.data.index + 1
      const next = this.data.queue[nextIndex] || null
      this.setData({
        submitting: false,
        lastSchedule: days,
        index: nextIndex,
        current: next,
        showAnswer: false,
        done: !next
      })
    } catch (err) {
      this.setData({ submitting: false, error: err.message || '提交失败' })
    }
  },

  onBack() {
    wx.switchTab({ url: '/pages/today/today' })
  },

  onRetry() {
    this.loadQueue()
  }
})
