var config = require('./config')
var httpModule = require('./services/http')
var authApiModule = require('./services/auth-api')

App({
  globalData: {
    apiBase: '',
    authState: 'booting',
    owner: null,
    environment: config.environment || 'development',
    bootPromise: null
  },

  onLaunch() {
    var client = httpModule.getDefaultClient()
    client.setEnvironment(config.environment || 'development')
    if (config.defaultApiBase) {
      var existing = client.getConfig().apiBase
      if (!existing || existing === 'http://127.0.0.1:8000') {
        // Prefer stored apiBase when the user already configured one.
        var stored = null
        try {
          stored = wx.getStorageSync('apiBase')
        } catch (e) {
          stored = null
        }
        if (!stored) {
          client.setApiBase(config.defaultApiBase)
        }
      }
    }

    var snap = client.loadFromStorage()
    this.globalData.apiBase = snap.apiBase
    this.globalData.authState = snap.authState
    this.globalData.owner = snap.owner
    this.globalData.environment = snap.environment

    var hasCredential = snap.hasSession || (snap.hasDevToken && snap.isDevConfigVisible)
    var autoLogin = Boolean(config.autoWeChatLogin) && !hasCredential

    this.globalData.bootPromise = authApiModule
      .getDefaultAuthApi()
      .bootstrap({ autoLogin: autoLogin })
      .then(
        function (result) {
          var next = client.getAuthSnapshot()
          this.globalData.apiBase = next.apiBase
          this.globalData.authState = result.authState || next.authState
          this.globalData.owner = result.owner || next.owner
          this.globalData.environment = next.environment
          return result
        }.bind(this)
      )
      .catch(
        function (err) {
          var next = client.getAuthSnapshot()
          this.globalData.authState = next.authState
          this.globalData.owner = next.owner
          return {
            authState: next.authState,
            owner: next.owner,
            source: 'none',
            error: err
          }
        }.bind(this)
      )
  },

  getAuthState: function () {
    return httpModule.getDefaultClient().getAuthSnapshot()
  },

  ensureAuthReady: function () {
    if (this.globalData.bootPromise) {
      return this.globalData.bootPromise
    }
    return Promise.resolve(this.getAuthState())
  }
})
