var api = require('../../services/api')

var STATE_LABELS = {
  booting: '启动中',
  authenticating: '登录中',
  ready: '已登录',
  unauthenticated: '未登录',
  forbidden: '无权限',
  offline: '离线',
  expired: '已过期',
  revoked: '已失效'
}

Page({
  data: {
    apiBase: '',
    token: '',
    showToken: false,
    showDevConfig: true,
    saving: false,
    loggingIn: false,
    loggingOut: false,
    error: '',
    ok: '',
    stats: {},
    connectionState: '未检测',
    authState: 'booting',
    authStateLabel: '启动中',
    ownerName: '',
    ownerId: null
  },

  onShow: function () {
    this.syncFromAuth()
    var snap = api.getAuthSnapshot()
    if (snap.authState === 'ready') {
      this.onRefreshStats()
    }
  },

  syncFromAuth: function () {
    var cfg = api.getConfig()
    var snap = api.getAuthSnapshot()
    var owner = snap.owner || {}
    this.setData({
      apiBase: cfg.apiBase,
      token: cfg.isDevConfigVisible ? cfg.token : '',
      showDevConfig: Boolean(cfg.isDevConfigVisible),
      authState: snap.authState,
      authStateLabel: STATE_LABELS[snap.authState] || snap.authState,
      ownerName: owner.display_name || (owner.id != null ? 'Owner #' + owner.id : ''),
      ownerId: owner.id != null ? owner.id : null,
      connectionState: this.connectionLabel(snap.authState)
    })
  },

  connectionLabel: function (authState) {
    if (authState === 'ready') return '连接正常'
    if (authState === 'offline') return '网络异常'
    if (authState === 'expired' || authState === 'revoked') return '登录失效'
    if (authState === 'forbidden') return '无权限'
    if (authState === 'authenticating' || authState === 'booting') return '检测中'
    return '未登录'
  },

  onApiBase: function (e) {
    this.setData({ apiBase: e.detail.value })
  },

  onToken: function (e) {
    this.setData({ token: e.detail.value })
  },

  onToggleToken: function () {
    this.setData({ showToken: !this.data.showToken })
  },

  onSave: function () {
    if (!this.data.showDevConfig) {
      this.setData({ error: '生产模式不支持手动填写 Token', ok: '' })
      return
    }
    var apiBase = String(this.data.apiBase || '').trim().replace(/\/$/, '')
    var token = String(this.data.token || '').trim()
    if (!apiBase || !token) {
      this.setData({
        error: '请完整填写 API 地址和开发 Token。',
        ok: '',
        connectionState: '未配置'
      })
      return
    }
    this.setData({ saving: true, error: '', ok: '' })
    api.saveConfig({ apiBase: apiBase, token: token })
    var self = this
    api
      .getHealth()
      .then(function () {
        return api.fetchMe()
      })
      .then(function (owner) {
        return api.getStats().then(function (stats) {
          return { owner: owner, stats: stats }
        })
      })
      .then(function (result) {
        self.syncFromAuth()
        self.setData({
          apiBase: apiBase,
          token: token,
          saving: false,
          ok: '连接成功',
          stats: result.stats || {},
          connectionState: '连接正常',
          ownerName:
            (result.owner && result.owner.display_name) ||
            (result.owner && result.owner.id != null ? 'Owner #' + result.owner.id : ''),
          ownerId: result.owner && result.owner.id != null ? result.owner.id : null
        })
      })
      .catch(function (e) {
        self.syncFromAuth()
        self.setData({
          saving: false,
          error: (e && e.message) || '连接失败',
          connectionState: '连接异常'
        })
      })
  },

  onWeChatLogin: function () {
    if (this.data.loggingIn) return
    this.setData({ loggingIn: true, error: '', ok: '' })
    var self = this
    api
      .loginWithWx()
      .then(function (payload) {
        self.syncFromAuth()
        self.setData({
          loggingIn: false,
          ok: '微信登录成功',
          connectionState: '连接正常',
          ownerName:
            (payload.owner && payload.owner.display_name) ||
            (payload.owner && payload.owner.id != null ? 'Owner #' + payload.owner.id : '')
        })
        return self.onRefreshStats()
      })
      .catch(function (e) {
        self.syncFromAuth()
        self.setData({
          loggingIn: false,
          error: (e && e.message) || '微信登录失败',
          connectionState: self.connectionLabel(api.getAuthSnapshot().authState)
        })
      })
  },

  onLogout: function () {
    if (this.data.loggingOut) return
    this.setData({ loggingOut: true, error: '', ok: '' })
    var self = this
    api
      .logout()
      .then(function () {
        self.syncFromAuth()
        self.setData({
          loggingOut: false,
          ok: '已退出登录',
          stats: {},
          connectionState: '未登录',
          token: self.data.showDevConfig ? api.getConfig().token : ''
        })
      })
      .catch(function (e) {
        self.syncFromAuth()
        self.setData({
          loggingOut: false,
          error: (e && e.message) || '退出失败'
        })
      })
  },

  onRefreshStats: function () {
    var self = this
    return api
      .getStats()
      .then(function (stats) {
        self.setData({ stats: stats || {}, error: '', connectionState: '连接正常' })
      })
      .catch(function (e) {
        self.syncFromAuth()
        self.setData({
          error: (e && e.message) || '统计加载失败',
          connectionState: self.connectionLabel(api.getAuthSnapshot().authState)
        })
      })
  }
})
