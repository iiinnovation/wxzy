/**
 * WeChat session auth API helpers.
 * Pages must not call wx.request or assemble Authorization headers.
 */

'use strict'

const httpModule = require('./http')

function createAuthApi(client, deps) {
  client = client || httpModule.getDefaultClient()
  deps = deps || {}
  const wxLogin = deps.wxLogin || defaultWxLogin
  const deviceLabel = deps.deviceLabel || defaultDeviceLabel

  function loginWithCode(code, label) {
    return client
      .request('/api/v1/auth/wechat', {
        method: 'POST',
        auth: false,
        retryOnUnauthorized: false,
        data: {
          code: code,
          device_label: label || deviceLabel()
        }
      })
      .then(function (payload) {
        client.setSession(payload)
        return payload
      })
  }

  function loginWithWx() {
    client.setAuthState(client.AUTH_STATE.AUTHENTICATING)
    return wxLogin()
      .then(function (code) {
        if (!code) {
          const err = httpModule.createApiError({
            code: 'WECHAT_LOGIN_FAILED',
            message: '微信登录失败，请重试',
            statusCode: 0
          })
          client.setAuthState(client.AUTH_STATE.UNAUTHENTICATED)
          throw err
        }
        return loginWithCode(code)
      })
      .catch(function (err) {
        if (err && err.offline) {
          client.setAuthState(client.AUTH_STATE.OFFLINE)
        } else if (err && err.code === 'OWNER_ALREADY_BOUND') {
          client.setAuthState(client.AUTH_STATE.FORBIDDEN)
        } else if (!(err && err.name === 'ApiError' && client.getAuthSnapshot().authState === client.AUTH_STATE.FORBIDDEN)) {
          if (!err || !err.offline) {
            const snap = client.getAuthSnapshot()
            if (snap.authState === client.AUTH_STATE.AUTHENTICATING) {
              client.setAuthState(client.AUTH_STATE.UNAUTHENTICATED)
            }
          }
        }
        throw err
      })
  }

  function refresh() {
    return client
      .request('/api/v1/auth/refresh', {
        method: 'POST',
        auth: true,
        skipRefresh: true,
        retryOnUnauthorized: false
      })
      .then(function (payload) {
        client.setSession(payload)
        return payload
      })
  }

  function logout() {
    const token = client.getBearerToken()
    if (!token || !client.getAuthSnapshot().hasSession) {
      client.clearSession(client.AUTH_STATE.UNAUTHENTICATED)
      return Promise.resolve({ ok: true, localOnly: true })
    }

    return client
      .request('/api/v1/auth/logout', {
        method: 'POST',
        auth: true,
        skipRefresh: true,
        retryOnUnauthorized: false
      })
      .then(function () {
        client.clearSession(client.AUTH_STATE.UNAUTHENTICATED)
        return { ok: true, localOnly: false }
      })
      .catch(function (err) {
        // logout is idempotent: always drop local session
        client.clearSession(client.AUTH_STATE.UNAUTHENTICATED)
        if (err && err.offline) {
          return { ok: true, localOnly: true, offline: true }
        }
        return { ok: true, localOnly: true, error: err }
      })
  }

  function fetchMe() {
    return client.request('/api/v1/me', {
      method: 'GET',
      auth: true
    }).then(function (owner) {
      if (owner && typeof owner === 'object' && client.setOwner) {
        client.setOwner(owner)
      }
      return owner
    })
  }

  function listSessions() {
    return client.request('/api/v1/me/sessions', {
      method: 'GET',
      auth: true
    })
  }

  function revokeSession(sessionId) {
    return client.request('/api/v1/me/sessions/' + Number(sessionId), {
      method: 'DELETE',
      auth: true
    })
  }

  function exportData() {
    return client.request('/api/v1/me/export', {
      method: 'GET',
      auth: true,
      timeout: 30000
    })
  }

  function deleteData() {
    // Confirmation travels in the query string because wx.request drops DELETE
    // bodies on some platforms (e.g. PC WeChat); the body is kept as a fallback.
    return client
      .request('/api/v1/me?confirmation=DELETE_MY_DATA', {
        method: 'DELETE',
        auth: true,
        data: { confirmation: 'DELETE_MY_DATA' }
      })
      .then(function () {
        client.clearSession(client.AUTH_STATE.UNAUTHENTICATED)
        if (client.isDevEnvironment() && client.setDevToken) {
          client.setDevToken('')
        }
        return { ok: true }
      })
  }

  /**
   * Boot sequence:
   * 1. load storage session
   * 2. if session present, GET /me (refresh on 401)
   * 3. else if wechat mode path requested, wx.login exchange
   * 4. else leave unauthenticated (dev can set token on Me page)
   */
  function bootstrap(options) {
    options = options || {}
    client.loadFromStorage()
    client.setAuthState(client.AUTH_STATE.BOOTING)
    client.setReauthHandler(function () {
      return loginWithWx().then(function (payload) {
        return payload
      })
    })

    const snap = client.getAuthSnapshot()

    if (snap.hasSession) {
      return fetchMe()
        .then(function (owner) {
          client.setAuthState(client.AUTH_STATE.READY)
          return {
            authState: client.AUTH_STATE.READY,
            owner: owner,
            source: 'session'
          }
        })
        .catch(function (err) {
          if (err && err.offline) {
            client.setAuthState(client.AUTH_STATE.OFFLINE)
            return {
              authState: client.AUTH_STATE.OFFLINE,
              owner: client.getAuthSnapshot().owner,
              source: 'cache',
              error: err
            }
          }
          if (options.autoLogin !== false) {
            return loginWithWx()
              .then(function (payload) {
                return {
                  authState: client.AUTH_STATE.READY,
                  owner: payload.owner,
                  source: 'wechat'
                }
              })
              .catch(function (loginErr) {
                return {
                  authState: client.getAuthSnapshot().authState,
                  owner: null,
                  source: 'none',
                  error: loginErr
                }
              })
          }
          return {
            authState: client.getAuthSnapshot().authState,
            owner: null,
            source: 'none',
            error: err
          }
        })
    }

    if (snap.hasDevToken && client.isDevEnvironment()) {
      return fetchMe()
        .then(function (owner) {
          client.setAuthState(client.AUTH_STATE.READY)
          return {
            authState: client.AUTH_STATE.READY,
            owner: owner,
            source: 'dev_token'
          }
        })
        .catch(function (err) {
          if (err && err.offline) {
            client.setAuthState(client.AUTH_STATE.OFFLINE)
            return {
              authState: client.AUTH_STATE.OFFLINE,
              owner: null,
              source: 'dev_token',
              error: err
            }
          }
          client.setAuthState(client.AUTH_STATE.UNAUTHENTICATED)
          return {
            authState: client.AUTH_STATE.UNAUTHENTICATED,
            owner: null,
            source: 'none',
            error: err
          }
        })
    }

    if (options.autoLogin) {
      return loginWithWx()
        .then(function (payload) {
          return {
            authState: client.AUTH_STATE.READY,
            owner: payload.owner,
            source: 'wechat'
          }
        })
        .catch(function (err) {
          return {
            authState: client.getAuthSnapshot().authState,
            owner: null,
            source: 'none',
            error: err
          }
        })
    }

    client.setAuthState(client.AUTH_STATE.UNAUTHENTICATED)
    return Promise.resolve({
      authState: client.AUTH_STATE.UNAUTHENTICATED,
      owner: null,
      source: 'none'
    })
  }

  return {
    loginWithCode: loginWithCode,
    loginWithWx: loginWithWx,
    refresh: refresh,
    logout: logout,
    fetchMe: fetchMe,
    listSessions: listSessions,
    revokeSession: revokeSession,
    exportData: exportData,
    deleteData: deleteData,
    bootstrap: bootstrap
  }
}

function defaultWxLogin() {
  return new Promise(function (resolve, reject) {
    if (typeof wx === 'undefined' || !wx.login) {
      reject(
        httpModule.createApiError({
          code: 'WECHAT_RUNTIME_MISSING',
          message: '当前环境无法调用微信登录',
          statusCode: 0
        })
      )
      return
    }
    wx.login({
      success: function (res) {
        if (res && res.code) {
          resolve(res.code)
          return
        }
        reject(
          httpModule.createApiError({
            code: 'WECHAT_LOGIN_FAILED',
            message: '微信登录失败，请重试',
            statusCode: 0
          })
        )
      },
      fail: function (err) {
        reject(
          httpModule.createApiError({
            code: 'WECHAT_LOGIN_FAILED',
            message: (err && err.errMsg) || '微信登录失败，请重试',
            statusCode: 0
          })
        )
      }
    })
  })
}

function defaultDeviceLabel() {
  try {
    if (typeof wx !== 'undefined' && wx.getSystemInfoSync) {
      const info = wx.getSystemInfoSync()
      const parts = [info.brand, info.model, info.system].filter(Boolean)
      return parts.join(' ').slice(0, 128) || 'wechat-miniprogram'
    }
  } catch (e) {
    // ignore
  }
  return 'wechat-miniprogram'
}

let defaultAuthApi = null

function getDefaultAuthApi() {
  if (!defaultAuthApi) {
    defaultAuthApi = createAuthApi()
  }
  return defaultAuthApi
}

function resetDefaultAuthApiForTests(api) {
  defaultAuthApi = api || null
}

module.exports = {
  createAuthApi: createAuthApi,
  getDefaultAuthApi: getDefaultAuthApi,
  resetDefaultAuthApiForTests: resetDefaultAuthApiForTests
}
