/**
 * Session-aware HTTP client for the miniprogram.
 *
 * Pages must not assemble Authorization headers. Callers go through request()
 * or domain helpers that use this module.
 *
 * Dependencies are injectable so Node unit tests can run without the WeChat runtime.
 */

'use strict'

var AUTH_STATE = {
  BOOTING: 'booting',
  AUTHENTICATING: 'authenticating',
  READY: 'ready',
  UNAUTHENTICATED: 'unauthenticated',
  FORBIDDEN: 'forbidden',
  OFFLINE: 'offline',
  EXPIRED: 'expired',
  REVOKED: 'revoked'
}

var STORAGE_KEYS = {
  API_BASE: 'apiBase',
  SESSION_TOKEN: 'sessionToken',
  SESSION_EXPIRES_AT: 'sessionExpiresAt',
  DEV_TOKEN: 'apiToken',
  ENVIRONMENT: 'clientEnvironment',
  OWNER_SUMMARY: 'ownerSummary'
}

var DEFAULT_TIMEOUT_MS = 15000
var DEFAULT_API_BASE = 'http://127.0.0.1:8000'

function createHttpClient(deps) {
  deps = deps || {}
  var storage = deps.storage || createWxStorageAdapter()
  var requestFn = deps.request || createWxRequestAdapter()
  var now = deps.now || function () {
    return Date.now()
  }
  var idFactory = deps.idFactory || createRequestIdFactory()
  var logger = deps.logger || { warn: function () {}, info: function () {} }

  var runtime = {
    apiBase: '',
    sessionToken: '',
    sessionExpiresAt: '',
    devToken: '',
    environment: 'development',
    authState: AUTH_STATE.BOOTING,
    owner: null,
    refreshInFlight: null,
    reauthHandler: null
  }

  function loadFromStorage() {
    var apiBase = normalizeBase(
      storage.get(STORAGE_KEYS.API_BASE) || DEFAULT_API_BASE
    )
    var sessionToken = String(storage.get(STORAGE_KEYS.SESSION_TOKEN) || '')
    var sessionExpiresAt = String(storage.get(STORAGE_KEYS.SESSION_EXPIRES_AT) || '')
    var devToken = String(storage.get(STORAGE_KEYS.DEV_TOKEN) || '')
    var environment = String(storage.get(STORAGE_KEYS.ENVIRONMENT) || 'development')
    var owner = storage.get(STORAGE_KEYS.OWNER_SUMMARY) || null

    runtime.apiBase = apiBase
    runtime.sessionToken = sessionToken
    runtime.sessionExpiresAt = sessionExpiresAt
    runtime.devToken = devToken
    runtime.environment = environment === 'production' ? 'production' : 'development'
    runtime.owner = owner && typeof owner === 'object' ? owner : null
    if (!isDevEnvironment() && runtime.devToken) {
      runtime.devToken = ''
      storage.remove(STORAGE_KEYS.DEV_TOKEN)
    }
    runtime.authState = resolveAuthState()
    return getAuthSnapshot()
  }

  function resolveAuthState() {
    if (!runtime.apiBase) {
      return AUTH_STATE.UNAUTHENTICATED
    }
    if (runtime.sessionToken) {
      if (isExpired(runtime.sessionExpiresAt, now())) {
        return AUTH_STATE.EXPIRED
      }
      return AUTH_STATE.READY
    }
    if (isDevEnvironment() && runtime.devToken) {
      return AUTH_STATE.READY
    }
    return AUTH_STATE.UNAUTHENTICATED
  }

  function isDevEnvironment() {
    return runtime.environment !== 'production'
  }

  function getBearerToken() {
    if (runtime.sessionToken) {
      return runtime.sessionToken
    }
    if (isDevEnvironment() && runtime.devToken) {
      return runtime.devToken
    }
    return ''
  }

  function setApiBase(apiBase) {
    runtime.apiBase = normalizeBase(apiBase || DEFAULT_API_BASE)
    storage.set(STORAGE_KEYS.API_BASE, runtime.apiBase)
  }

  function setEnvironment(environment) {
    runtime.environment = environment === 'production' ? 'production' : 'development'
    storage.set(STORAGE_KEYS.ENVIRONMENT, runtime.environment)
    if (!isDevEnvironment()) {
      clearDevToken()
    }
    runtime.authState = resolveAuthState()
  }

  function setSession(session) {
    session = session || {}
    var token = String(session.access_token || session.token || '')
    var expiresAt = session.expires_at || session.expiresAt || ''
    var owner = session.owner || null

    runtime.sessionToken = token
    runtime.sessionExpiresAt = expiresAt ? String(expiresAt) : ''
    runtime.owner = owner && typeof owner === 'object' ? owner : null
    runtime.authState = token
      ? isExpired(runtime.sessionExpiresAt, now())
        ? AUTH_STATE.EXPIRED
        : AUTH_STATE.READY
      : AUTH_STATE.UNAUTHENTICATED

    if (token) {
      storage.set(STORAGE_KEYS.SESSION_TOKEN, token)
      storage.set(STORAGE_KEYS.SESSION_EXPIRES_AT, runtime.sessionExpiresAt)
    } else {
      storage.remove(STORAGE_KEYS.SESSION_TOKEN)
      storage.remove(STORAGE_KEYS.SESSION_EXPIRES_AT)
    }

    if (runtime.owner) {
      storage.set(STORAGE_KEYS.OWNER_SUMMARY, runtime.owner)
    } else {
      storage.remove(STORAGE_KEYS.OWNER_SUMMARY)
    }
  }

  function clearSession(nextState) {
    runtime.sessionToken = ''
    runtime.sessionExpiresAt = ''
    runtime.owner = null
    runtime.authState = nextState || AUTH_STATE.UNAUTHENTICATED
    storage.remove(STORAGE_KEYS.SESSION_TOKEN)
    storage.remove(STORAGE_KEYS.SESSION_EXPIRES_AT)
    storage.remove(STORAGE_KEYS.OWNER_SUMMARY)
  }

  function setOwner(owner) {
    runtime.owner = owner && typeof owner === 'object' ? owner : null
    if (runtime.owner) {
      storage.set(STORAGE_KEYS.OWNER_SUMMARY, runtime.owner)
    } else {
      storage.remove(STORAGE_KEYS.OWNER_SUMMARY)
    }
  }

  function setDevToken(token) {
    if (!isDevEnvironment()) {
      return
    }
    runtime.devToken = String(token || '')
    if (runtime.devToken) {
      storage.set(STORAGE_KEYS.DEV_TOKEN, runtime.devToken)
    } else {
      storage.remove(STORAGE_KEYS.DEV_TOKEN)
    }
    if (!runtime.sessionToken) {
      runtime.authState = runtime.devToken ? AUTH_STATE.READY : AUTH_STATE.UNAUTHENTICATED
    }
  }

  function clearDevToken() {
    runtime.devToken = ''
    storage.remove(STORAGE_KEYS.DEV_TOKEN)
  }

  function setAuthState(state) {
    runtime.authState = state
  }

  function setReauthHandler(handler) {
    runtime.reauthHandler = typeof handler === 'function' ? handler : null
  }

  function getAuthSnapshot() {
    return {
      authState: runtime.authState,
      apiBase: runtime.apiBase,
      hasSession: Boolean(runtime.sessionToken),
      hasDevToken: Boolean(runtime.devToken),
      sessionExpiresAt: runtime.sessionExpiresAt,
      environment: runtime.environment,
      isDevConfigVisible: isDevEnvironment(),
      owner: runtime.owner
    }
  }

  /**
   * @param {string} path
   * @param {object} [options]
   * @param {string} [options.method]
   * @param {object} [options.data]
   * @param {object} [options.header]
   * @param {number} [options.timeout]
   * @param {boolean} [options.auth=true] attach bearer when true
   * @param {boolean} [options.retryOnUnauthorized=true]
   * @param {boolean} [options.skipRefresh=false]
   */
  function request(path, options) {
    options = options || {}
    var method = (options.method || 'GET').toUpperCase()
    var useAuth = options.auth !== false
    var retryOnUnauthorized = options.retryOnUnauthorized !== false
    var skipRefresh = options.skipRefresh === true
    var requestId = options.requestId || idFactory()
    var timeout = options.timeout || DEFAULT_TIMEOUT_MS
    var url = joinUrl(runtime.apiBase || DEFAULT_API_BASE, path)

    var headers = {
      'Content-Type': 'application/json',
      'X-Request-Id': requestId
    }
    if (options.header) {
      Object.keys(options.header).forEach(function (key) {
        headers[key] = options.header[key]
      })
    }

    if (useAuth) {
      var token = getBearerToken()
      if (token) {
        headers.Authorization = 'Bearer ' + token
      }
    }

    return requestFn({
      url: url,
      method: method,
      data: options.data,
      header: headers,
      timeout: timeout
    }).then(function (res) {
      return handleResponse(res, {
        path: path,
        method: method,
        data: options.data,
        header: options.header,
        timeout: timeout,
        auth: useAuth,
        retryOnUnauthorized: retryOnUnauthorized,
        skipRefresh: skipRefresh,
        requestId: requestId
      })
    }).catch(function (err) {
      if (err && err.name === 'ApiError') {
        throw err
      }
      runtime.authState = AUTH_STATE.OFFLINE
      throw createApiError({
        code: 'NETWORK_ERROR',
        message: userMessageForNetwork(err),
        statusCode: 0,
        requestId: requestId,
        retriable: true,
        offline: true
      })
    })
  }

  function handleResponse(res, context) {
    var statusCode = res && typeof res.statusCode === 'number' ? res.statusCode : 0
    var body = res ? res.data : null
    var requestId =
      (res && res.header && (res.header['X-Request-Id'] || res.header['x-request-id'])) ||
      context.requestId

    if (statusCode >= 200 && statusCode < 300) {
      if (runtime.authState === AUTH_STATE.OFFLINE) {
        runtime.authState = resolveAuthState()
      }
      return body
    }

    if (statusCode === 401 && context.auth && context.retryOnUnauthorized && !context.skipRefresh) {
      return recoverFromUnauthorized(context, body, requestId)
    }

    if (statusCode === 401) {
      markUnauthorized(body)
      throw createApiError(normalizeErrorBody(body, {
        code: 'AUTH_REQUIRED',
        message: '登录已失效，请重新登录',
        statusCode: 401,
        requestId: requestId
      }))
    }

    if (statusCode === 403) {
      var forbidden = normalizeErrorBody(body, {
        code: 'FORBIDDEN',
        message: '当前微信身份无法访问此学习账户',
        statusCode: 403,
        requestId: requestId
      })
      if (forbidden.code === 'OWNER_ALREADY_BOUND') {
        runtime.authState = AUTH_STATE.FORBIDDEN
      }
      throw createApiError(forbidden)
    }

    throw createApiError(normalizeErrorBody(body, {
      code: 'HTTP_ERROR',
      message: '请求失败，请稍后重试',
      statusCode: statusCode,
      requestId: requestId
    }))
  }

  function recoverFromUnauthorized(context, body, requestId) {
    var hadSession = Boolean(runtime.sessionToken)
    return ensureFreshSession().then(function (refreshed) {
      if (!refreshed) {
        if (runtime.authState === AUTH_STATE.OFFLINE) {
          throw createApiError({
            code: 'NETWORK_ERROR',
            message: '网络不可用，请检查连接后重试',
            statusCode: 0,
            requestId: requestId,
            retriable: true,
            offline: true
          })
        }
        if (runtime.authState !== AUTH_STATE.REVOKED && runtime.authState !== AUTH_STATE.EXPIRED) {
          markUnauthorized(body)
        }
        var code = runtime.authState === AUTH_STATE.REVOKED
          ? 'SESSION_REVOKED'
          : hadSession
            ? 'SESSION_EXPIRED'
            : 'AUTH_REQUIRED'
        var message = code === 'SESSION_REVOKED'
          ? '登录已失效，请重新登录'
          : hadSession
            ? '登录已过期，请重新登录'
            : '请先登录'
        throw createApiError(normalizeErrorBody(body, {
          code: code,
          message: message,
          statusCode: 401,
          requestId: requestId
        }))
      }
      return request(context.path, {
        method: context.method,
        data: context.data,
        header: context.header,
        timeout: context.timeout,
        auth: context.auth,
        retryOnUnauthorized: false,
        skipRefresh: true,
        requestId: context.requestId
      })
    })
  }

  function ensureFreshSession() {
    if (!runtime.sessionToken) {
      return Promise.resolve(false)
    }
    if (runtime.refreshInFlight) {
      return runtime.refreshInFlight
    }

    runtime.refreshInFlight = request('/api/v1/auth/refresh', {
      method: 'POST',
      auth: true,
      skipRefresh: true,
      retryOnUnauthorized: false
    }).then(function (payload) {
      if (!payload || !payload.access_token) {
        clearSession(AUTH_STATE.REVOKED)
        return false
      }
      setSession(payload)
      return true
    }).catch(function (err) {
      if (err && err.offline) {
        runtime.authState = AUTH_STATE.OFFLINE
        return false
      }
      var code = err && err.code
      if (code === 'SESSION_REVOKED' || (err && err.statusCode === 401 && bodyLooksRevoked(err))) {
        clearSession(AUTH_STATE.REVOKED)
      } else if (code === 'SESSION_EXPIRED' || (err && err.statusCode === 401)) {
        clearSession(AUTH_STATE.EXPIRED)
      } else {
        clearSession(AUTH_STATE.UNAUTHENTICATED)
      }
      return tryReauthenticate().then(function (ok) {
        return ok
      })
    }).then(function (ok) {
      runtime.refreshInFlight = null
      return ok
    }, function (err) {
      runtime.refreshInFlight = null
      throw err
    })

    return runtime.refreshInFlight
  }

  function tryReauthenticate() {
    if (!runtime.reauthHandler) {
      return Promise.resolve(false)
    }
    runtime.authState = AUTH_STATE.AUTHENTICATING
    return Promise.resolve()
      .then(function () {
        return runtime.reauthHandler()
      })
      .then(function (session) {
        if (!session || !(session.access_token || session.token)) {
          runtime.authState = AUTH_STATE.UNAUTHENTICATED
          return false
        }
        setSession(session)
        return true
      })
      .catch(function (err) {
        if (err && err.offline) {
          runtime.authState = AUTH_STATE.OFFLINE
        } else if (err && err.code === 'OWNER_ALREADY_BOUND') {
          runtime.authState = AUTH_STATE.FORBIDDEN
        } else {
          runtime.authState = AUTH_STATE.UNAUTHENTICATED
        }
        logger.warn('reauth failed', err && err.code)
        return false
      })
  }

  function markUnauthorized(body) {
    var code = body && body.code
    if (code === 'SESSION_REVOKED') {
      clearSession(AUTH_STATE.REVOKED)
      return
    }
    if (code === 'SESSION_EXPIRED') {
      clearSession(AUTH_STATE.EXPIRED)
      return
    }
    if (runtime.sessionToken) {
      clearSession(AUTH_STATE.EXPIRED)
      return
    }
    runtime.authState = AUTH_STATE.UNAUTHENTICATED
  }

  function bodyLooksRevoked(err) {
    var message = String((err && err.message) || '')
    return message.indexOf('撤销') >= 0 || message.indexOf('revok') >= 0
  }

  function getConfig() {
    return {
      apiBase: runtime.apiBase || DEFAULT_API_BASE,
      token: getBearerToken(),
      hasSession: Boolean(runtime.sessionToken),
      environment: runtime.environment,
      isDevConfigVisible: isDevEnvironment()
    }
  }

  function saveConfig(config) {
    config = config || {}
    if (config.apiBase != null) {
      setApiBase(config.apiBase)
    }
    if (config.environment != null) {
      setEnvironment(config.environment)
    }
    if (config.token != null && isDevEnvironment()) {
      setDevToken(config.token)
    }
    runtime.authState = resolveAuthState()
    return getConfig()
  }

  // bootstrap
  loadFromStorage()

  return {
    AUTH_STATE: AUTH_STATE,
    STORAGE_KEYS: STORAGE_KEYS,
    loadFromStorage: loadFromStorage,
    request: request,
    getAuthSnapshot: getAuthSnapshot,
    getConfig: getConfig,
    saveConfig: saveConfig,
    setApiBase: setApiBase,
    setEnvironment: setEnvironment,
    setSession: setSession,
    clearSession: clearSession,
    setOwner: setOwner,
    setDevToken: setDevToken,
    clearDevToken: clearDevToken,
    setAuthState: setAuthState,
    setReauthHandler: setReauthHandler,
    ensureFreshSession: ensureFreshSession,
    getBearerToken: getBearerToken,
    isDevEnvironment: isDevEnvironment,
    // exposed for tests
    _runtime: runtime
  }
}

function normalizeBase(value) {
  return String(value || '').replace(/\/$/, '')
}

function joinUrl(base, path) {
  var normalizedBase = normalizeBase(base)
  if (!path) {
    return normalizedBase
  }
  if (/^https?:\/\//i.test(path)) {
    return path
  }
  return normalizedBase + (path.charAt(0) === '/' ? path : '/' + path)
}

function isExpired(expiresAt, nowMs) {
  if (!expiresAt) {
    return false
  }
  var ms = Date.parse(String(expiresAt))
  if (Number.isNaN(ms)) {
    return false
  }
  // refresh a little early to avoid edge races
  return ms <= nowMs + 5000
}

function createRequestIdFactory() {
  var counter = 0
  return function () {
    counter += 1
    return 'mp_' + Date.now().toString(36) + '_' + counter.toString(36)
  }
}

function createWxStorageAdapter() {
  return {
    get: function (key) {
      try {
        return wx.getStorageSync(key)
      } catch (e) {
        return ''
      }
    },
    set: function (key, value) {
      try {
        wx.setStorageSync(key, value)
      } catch (e) {
        // ignore storage failures; auth will fall back to memory
      }
    },
    remove: function (key) {
      try {
        wx.removeStorageSync(key)
      } catch (e) {
        // ignore
      }
    }
  }
}

function createWxRequestAdapter() {
  return function (options) {
    return new Promise(function (resolve, reject) {
      wx.request({
        url: options.url,
        method: options.method,
        data: options.data,
        header: options.header,
        timeout: options.timeout,
        success: function (res) {
          resolve(res)
        },
        fail: function (err) {
          reject(err || new Error('network error'))
        }
      })
    })
  }
}

function createApiError(fields) {
  var error = new Error(fields.message || 'request failed')
  error.name = 'ApiError'
  error.code = fields.code || 'HTTP_ERROR'
  error.statusCode = fields.statusCode || 0
  error.requestId = fields.requestId || null
  error.details = fields.details != null ? fields.details : null
  error.retriable = Boolean(fields.retriable)
  error.offline = Boolean(fields.offline)
  return error
}

function normalizeErrorBody(body, fallback) {
  if (!body || typeof body !== 'object') {
    return {
      code: fallback.code,
      message: fallback.message,
      statusCode: fallback.statusCode,
      requestId: fallback.requestId,
      details: null
    }
  }

  var message = body.message || body.detail || fallback.message
  if (typeof message !== 'string') {
    try {
      message = JSON.stringify(message)
    } catch (e) {
      message = fallback.message
    }
  }

  return {
    code: body.code || fallback.code,
    message: message,
    statusCode: fallback.statusCode,
    requestId: body.request_id || fallback.requestId,
    details: body.details != null ? body.details : null
  }
}

function userMessageForNetwork(err) {
  var msg = (err && (err.errMsg || err.message)) || ''
  if (/timeout/i.test(msg)) {
    return '网络超时，请检查连接后重试'
  }
  return '网络不可用，请检查连接后重试'
}

var defaultClient = null

function getDefaultClient() {
  if (!defaultClient) {
    defaultClient = createHttpClient()
  }
  return defaultClient
}

function resetDefaultClientForTests(client) {
  defaultClient = client || null
}

module.exports = {
  AUTH_STATE: AUTH_STATE,
  STORAGE_KEYS: STORAGE_KEYS,
  createHttpClient: createHttpClient,
  getDefaultClient: getDefaultClient,
  resetDefaultClientForTests: resetDefaultClientForTests,
  createApiError: createApiError,
  isExpired: isExpired,
  joinUrl: joinUrl
}
