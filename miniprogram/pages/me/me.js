const api = require('../../services/api')

Page({
  data: {
    apiBase: '',
    token: '',
    showToken: false,
    saving: false,
    error: '',
    ok: '',
    stats: {},
    connectionState: '未检测'
  },

  onShow() {
    const cfg = api.getConfig()
    this.setData({
      apiBase: cfg.apiBase,
      token: cfg.token,
      connectionState: cfg.token ? '待检测' : '未配置'
    })
    if (cfg.token) this.onRefreshStats()
  },

  onApiBase(e) {
    this.setData({ apiBase: e.detail.value })
  },

  onToken(e) {
    this.setData({ token: e.detail.value })
  },

  onToggleToken() {
    this.setData({ showToken: !this.data.showToken })
  },

  async onSave() {
    const apiBase = String(this.data.apiBase || '').trim().replace(/\/$/, '')
    const token = String(this.data.token || '').trim()
    if (!apiBase || !token) {
      this.setData({
        error: '请完整填写 API 地址和 Token。',
        ok: '',
        connectionState: '未配置'
      })
      return
    }
    this.setData({ saving: true, error: '', ok: '' })
    api.saveConfig({ apiBase, token })
    try {
      const health = await api.getHealth()
      const stats = await api.getStats()
      this.setData({
        apiBase,
        token,
        saving: false,
        ok: '连接成功：' + (health.app || 'api'),
        stats: stats || {},
        connectionState: '连接正常'
      })
    } catch (e) {
      this.setData({
        saving: false,
        error: e.message || '连接失败',
        connectionState: '连接异常'
      })
    }
  },

  async onRefreshStats() {
    try {
      const stats = await api.getStats()
      this.setData({ stats: stats || {}, error: '', connectionState: '连接正常' })
    } catch (e) {
      this.setData({ error: e.message || '统计加载失败', connectionState: '连接异常' })
    }
  }
})
