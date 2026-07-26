'use strict'

function createPageRequestGuard() {
  let sequence = 0
  let active = true

  return {
    begin: function () {
      sequence += 1
      active = true
      return sequence
    },
    isCurrent: function (value) {
      return active && value === sequence
    },
    invalidate: function () {
      sequence += 1
    },
    dispose: function () {
      active = false
      sequence += 1
    }
  }
}

function errorView(error, fallback) {
  const code = String((error && error.code) || '')
  return {
    message: (error && error.message) || fallback || '加载失败，请重试',
    unauthorized: Boolean(
      (error && error.statusCode === 401) ||
      code === 'AUTH_REQUIRED' ||
      code === 'SESSION_EXPIRED' ||
      code === 'SESSION_REVOKED'
    ),
    offline: Boolean(error && error.offline),
    retriable: error ? error.retriable !== false : true
  }
}

function canRetrySameWrite(error) {
  return Boolean(error && error.retriable === true)
}

// Shared page-load sequence: ensure auth is ready, gate on an authorization
// predicate, run the fetch, and route the outcome — with stale responses
// dropped via the guard at every stage. `fetch` receives an isCurrent()
// callback for multi-step fetches that update state between requests.
function loadWithAuth(guard, opts) {
  const sequence = guard.begin()
  const app = typeof getApp === 'function' ? getApp() : null
  return Promise.resolve(app && app.ensureAuthReady ? app.ensureAuthReady() : null)
    .then(function () {
      if (!guard.isCurrent(sequence)) return null
      if (opts.authorized && !opts.authorized()) {
        if (opts.onUnauthorized) opts.onUnauthorized()
        return null
      }
      return opts.fetch(function () {
        return guard.isCurrent(sequence)
      })
    })
    .then(function (result) {
      if (result === null || result === undefined) return
      if (!guard.isCurrent(sequence)) return
      opts.onReady(result)
    })
    .catch(function (error) {
      if (!guard.isCurrent(sequence)) return
      opts.onError(errorView(error, opts.fallback))
    })
}

module.exports = {
  createPageRequestGuard: createPageRequestGuard,
  errorView: errorView,
  canRetrySameWrite: canRetrySameWrite,
  loadWithAuth: loadWithAuth
}
