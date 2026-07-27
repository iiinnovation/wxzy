const api = require('../../services/api')
const requests = require('../../utils/page-request')
const format = require('../../utils/format')

const STATE_LABELS = {
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
    showDevConfig: false,
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
    ownerId: null,
    profileSummary: {
      goalLabel: '未设置',
      minutesLabel: '—',
      daysLabel: '—',
      onboardingDone: false,
      subjectsLabel: '未设置学科优先级'
    },
    needsOnboarding: false,
    accountState: 'idle',
    accountError: null,
    sessions: [],
    sessionActionId: 0,
    exporting: false,
    deleting: false
  },

  onLoad: function () {
    this.guard = requests.createPageRequestGuard()
  },

  onShow: function () {
    this.syncFromAuth()
    const snap = api.getAuthSnapshot()
    if (snap.authState === 'ready') {
      this.loadAccountData()
    } else {
      this.setData({ accountState: 'idle', sessions: [] })
    }
  },

  onUnload: function () {
    this.guard.dispose()
  },

  syncFromAuth: function () {
    const cfg = api.getConfig()
    const snap = api.getAuthSnapshot()
    const owner = snap.owner || {}
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
    const apiBase = String(this.data.apiBase || '').trim().replace(/\/$/, '')
    const token = String(this.data.token || '').trim()
    if (!apiBase) {
      this.setData({
        error: '请填写 API 地址。',
        ok: '',
        connectionState: '未配置'
      })
      return
    }
    this.setData({ saving: true, error: '', ok: '' })
    api.saveConfig({ apiBase: apiBase, token: token })
    const self = this
    api
      .getHealth()
      .then(function () {
        if (!token) {
          self.syncFromAuth()
          self.setData({
            apiBase: apiBase,
            token: '',
            saving: false,
            ok: '服务可达，请点击微信登录',
            connectionState: '未登录'
          })
          return null
        }
        return api.fetchMe()
      })
      .then(function (owner) {
        if (!token) return null
        return api.getStats().then(function (stats) {
          return { owner: owner, stats: stats }
        })
      })
      .then(function (result) {
        if (!result) return null
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
        return self.loadAccountData()
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
    const self = this
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
        return self.loadAccountData()
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
    const self = this
    api
      .logout()
      .then(function () {
        self.syncFromAuth()
        self.setData({
          loggingOut: false,
          ok: '已退出登录',
          stats: {},
          sessions: [],
          accountState: 'idle',
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

  loadAccountData: function () {
    const sequence = this.guard.begin()
    const self = this
    this.setData({ accountState: 'loading', accountError: null })
    const settle = function (promise) {
      return promise.then(
        function (value) {
          return { ok: true, value: value }
        },
        function (error) {
          return { ok: false, error: error }
        }
      )
    }
    return Promise.all([
      settle(api.getStats()),
      settle(api.getLearningProfile()),
      settle(api.listSessions())
    ]).then(function (results) {
      if (!self.guard.isCurrent(sequence)) return
      const failed = results.filter(function (result) {
        return !result.ok
      })
      const view = failed.length ? requests.errorView(failed[0].error) : null
      if (failed.length === results.length || (view && view.unauthorized)) {
        self.syncFromAuth()
        self.setData({
          accountState: view.unauthorized ? 'unauthorized' : 'error',
          accountError: view,
          error: view.message,
          connectionState: self.connectionLabel(api.getAuthSnapshot().authState)
        })
        return
      }
      // Partial failure: keep the sections that loaded, surface the error inline.
      const update = {
        accountState: 'ready',
        connectionState: '连接正常'
      }
      if (results[0].ok) update.stats = results[0].value || {}
      if (results[1].ok) {
        const summary = api.summarizeProfile(results[1].value)
        update.profileSummary = summary
        update.needsOnboarding = !summary.onboardingDone
        update.ownerName =
          summary.displayName ||
          self.data.ownerName ||
          (self.data.ownerId != null ? 'Owner #' + self.data.ownerId : '')
      }
      if (results[2].ok) {
        const sessionPage = results[2].value || { items: [] }
        update.sessions = self.formatSessions(sessionPage.items || [])
      }
      if (view) {
        update.accountError = view
        update.error = view.message
      }
      self.setData(update)
    })
  },

  formatSessions: function (rows) {
    const statusLabels = { active: '有效', expired: '已过期', revoked: '已撤销' }
    return rows.map(function (row) {
      return Object.assign({}, row, {
        deviceLabel: row.device_label || '微信小程序设备',
        createdLabel: format.dateTimeLabel(row.created_at),
        expiresLabel: format.dateTimeLabel(row.expires_at),
        statusLabel: statusLabels[row.status] || row.status
      })
    })
  },

  onOpenOnboarding: function () {
    wx.navigateTo({ url: '/pages/onboarding/onboarding' })
  },

  onOpenProfileEdit: function () {
    wx.navigateTo({ url: '/pages/profile-edit/profile-edit' })
  },

  onRefreshStats: function () {
    if (this.data.accountState !== 'loading') return this.loadAccountData()
    return Promise.resolve()
  },

  onRevokeSession: function (event) {
    const id = Number(event.currentTarget.dataset.id)
    if (!id || this.data.sessionActionId) return
    const self = this
    wx.showModal({
      title: '撤销登录设备',
      content: '该设备下次访问时需要重新登录。',
      confirmText: '撤销',
      success: function (result) {
        if (!result.confirm) return
        self.setData({ sessionActionId: id, error: '', ok: '' })
        api
          .revokeSession(id)
          .then(function () {
            self.setData({ sessionActionId: 0, ok: '设备已撤销' })
            return self.loadAccountData()
          })
          .catch(function (error) {
            self.setData({
              sessionActionId: 0,
              error: (error && error.message) || '撤销失败'
            })
          })
      }
    })
  },

  onExportData: function () {
    if (this.data.exporting) return
    const self = this
    this.setData({ exporting: true, error: '', ok: '' })
    api
      .exportOwnerData()
      .then(function (payload) {
        const text = JSON.stringify(payload, null, 2)
        wx.setClipboardData({
          data: text,
          success: function () {
            self.setData({ exporting: false, ok: '数据已复制到剪贴板' })
          },
          fail: function () {
            self.setData({ exporting: false, error: '导出已生成，但复制失败，请重试' })
          }
        })
      })
      .catch(function (error) {
        self.setData({
          exporting: false,
          error: (error && error.message) || '数据导出失败'
        })
      })
  },

  onDeleteData: function () {
    if (this.data.deleting) return
    const self = this
    wx.showModal({
      title: '删除全部学习数据',
      content: '此操作不可恢复，将删除档案、加入状态、复习记录和所有登录设备。共享书籍目录不会删除。',
      confirmText: '确认删除',
      confirmColor: '#a53d3d',
      success: function (result) {
        if (!result.confirm) return
        self.setData({ deleting: true, error: '', ok: '' })
        api
          .deleteOwnerData()
          .then(function () {
            self.syncFromAuth()
            self.setData({
              deleting: false,
              accountState: 'idle',
              sessions: [],
              stats: {},
              ok: '学习数据已删除'
            })
          })
          .catch(function (error) {
            self.setData({
              deleting: false,
              error: (error && error.message) || '删除失败'
            })
          })
      }
    })
  }
})
