const api = require('../../services/api')

Page({
  data: {
    loading: false,
    error: '',
    books: [],
    cards: [],
    activeBookId: null,
    activeBookName: '',
    keyword: '',
    expandedCardId: null
  },

  onShow() {
    this.loadBooks()
  },

  async loadBooks() {
    this.setData({ loading: true, error: '' })
    try {
      const books = await api.getBooks()
      this.setData({ books: books || [], loading: false })
    } catch (e) {
      this.setData({ loading: false, error: e.message || '加载失败' })
    }
  },

  async onOpenBook(e) {
    const id = Number(e.currentTarget.dataset.id)
    const name = e.currentTarget.dataset.name
    this.setData({
      loading: true,
      error: '',
      activeBookId: id,
      activeBookName: name,
      expandedCardId: null
    })
    try {
      const cards = await api.getCards({ book_id: id, q: this.data.keyword, limit: 50 })
      this.setData({ cards: cards || [], loading: false })
    } catch (err) {
      this.setData({ loading: false, error: err.message || '加载卡片失败' })
    }
  },

  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value })
  },

  async onSearch() {
    if (!this.data.activeBookId) return
    await this.onOpenBook({
      currentTarget: {
        dataset: { id: this.data.activeBookId, name: this.data.activeBookName }
      }
    })
  },

  onBackBooks() {
    this.setData({
      activeBookId: null,
      activeBookName: '',
      cards: [],
      keyword: '',
      expandedCardId: null
    })
  },

  onToggleCard(e) {
    const id = Number(e.currentTarget.dataset.id)
    this.setData({ expandedCardId: this.data.expandedCardId === id ? null : id })
  }
})
