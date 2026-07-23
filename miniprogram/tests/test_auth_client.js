#!/usr/bin/env node
/**
 * Node unit tests for miniprogram session-aware auth client.
 * Run: node miniprogram/tests/test_auth_client.js
 */
'use strict'

var assert = require('assert')
var path = require('path')

var httpModule = require(path.join(__dirname, '..', 'services', 'http.js'))
var authApiModule = require(path.join(__dirname, '..', 'services', 'auth-api.js'))
var fixtures = require(path.join(__dirname, 'fixtures', 'auth-responses.js'))

var failures = 0
var passed = 0

function test(name, fn) {
  try {
    var result = fn()
    if (result && typeof result.then === 'function') {
      return result.then(
        function () {
          passed += 1
          console.log('ok - ' + name)
        },
        function (err) {
          failures += 1
          console.error('not ok - ' + name)
          console.error('  ' + (err && err.stack ? err.stack : err))
        }
      )
    }
    passed += 1
    console.log('ok - ' + name)
    return Promise.resolve()
  } catch (err) {
    failures += 1
    console.error('not ok - ' + name)
    console.error('  ' + (err && err.stack ? err.stack : err))
    return Promise.resolve()
  }
}

function createMemoryStorage(seed) {
  var data = Object.assign({}, seed || {})
  return {
    get: function (key) {
      return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : ''
    },
    set: function (key, value) {
      data[key] = value
    },
    remove: function (key) {
      delete data[key]
    },
    dump: function () {
      return Object.assign({}, data)
    }
  }
}

function createMockRequest(router) {
  var calls = []
  function requestFn(options) {
    calls.push({
      url: options.url,
      method: options.method,
      header: Object.assign({}, options.header || {}),
      data: options.data
    })
    return Promise.resolve().then(function () {
      return router(options, calls)
    })
  }
  requestFn.calls = calls
  return requestFn
}

function pathOf(url) {
  var idx = url.indexOf('/api/')
  if (idx >= 0) return url.slice(idx)
  var health = url.indexOf('/health')
  if (health >= 0) return url.slice(health)
  var stats = url.indexOf('/stats')
  if (stats >= 0) return url.slice(stats)
  try {
    return url.replace(/^https?:\/\/[^/]+/, '') || '/'
  } catch (e) {
    return url
  }
}

function assertNoPageAuthPattern() {
  // Pages should not assemble Authorization headers themselves.
  var fs = require('fs')
  var root = path.join(__dirname, '..', 'pages')
  var offenders = []
  function walk(dir) {
    fs.readdirSync(dir).forEach(function (name) {
      var full = path.join(dir, name)
      var st = fs.statSync(full)
      if (st.isDirectory()) {
        walk(full)
        return
      }
      if (!name.endsWith('.js')) return
      var text = fs.readFileSync(full, 'utf8')
      if (/Authorization\s*:/.test(text) || /['"]Bearer\s/.test(text)) {
        offenders.push(full)
      }
    })
  }
  walk(root)
  assert.deepStrictEqual(offenders, [], 'pages must not assemble auth headers: ' + offenders.join(', '))
}

function run() {
  var chain = Promise.resolve()

  chain = chain.then(function () {
    return test('pages do not assemble Authorization headers', function () {
      assertNoPageAuthPattern()
    })
  })

  chain = chain.then(function () {
    return test('loads valid session from storage and attaches bearer', function () {
      var storage = createMemoryStorage({
        apiBase: 'http://127.0.0.1:8000',
        sessionToken: 'session-token-valid-0001',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString(),
        clientEnvironment: 'development'
      })
      var requestFn = createMockRequest(function (options) {
        assert.strictEqual(options.header.Authorization, 'Bearer session-token-valid-0001')
        assert.ok(options.header['X-Request-Id'])
        return fixtures.ok({ id: 1, status: 'active', display_name: '学习者', timezone: 'Asia/Shanghai' })
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      assert.strictEqual(client.getAuthSnapshot().authState, 'ready')
      return client.request('/api/v1/me').then(function (body) {
        assert.strictEqual(body.id, 1)
        assert.strictEqual(requestFn.calls.length, 1)
      })
    })
  })

  chain = chain.then(function () {
    return test('expired session storage maps to expired state', function () {
      var storage = createMemoryStorage({
        sessionToken: 'old',
        sessionExpiresAt: new Date(Date.now() - 1000).toISOString()
      })
      var client = httpModule.createHttpClient({
        storage: storage,
        request: createMockRequest(function () {
          return fixtures.ok({})
        })
      })
      assert.strictEqual(client.getAuthSnapshot().authState, 'expired')
      assert.strictEqual(client.getAuthSnapshot().hasSession, true)
    })
  })

  chain = chain.then(function () {
    return test('401 refresh rotates token and retries original request', function () {
      var storage = createMemoryStorage({
        apiBase: 'http://example.test',
        sessionToken: 'old-token',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString()
      })
      var requestFn = createMockRequest(function (options) {
        var p = pathOf(options.url)
        if (p === '/api/v1/me' && options.header.Authorization === 'Bearer old-token') {
          return fixtures.unauthorizedExpired()
        }
        if (p === '/api/v1/auth/refresh') {
          assert.strictEqual(options.header.Authorization, 'Bearer old-token')
          return fixtures.ok(fixtures.refreshedSession())
        }
        if (p === '/api/v1/me' && options.header.Authorization === 'Bearer session-token-refreshed-0002') {
          return fixtures.ok(fixtures.OWNER)
        }
        throw new Error('unexpected call ' + p + ' ' + options.header.Authorization)
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      return client.request('/api/v1/me').then(function (owner) {
        assert.strictEqual(owner.id, 1)
        assert.strictEqual(client.getBearerToken(), 'session-token-refreshed-0002')
        assert.strictEqual(storage.get('sessionToken'), 'session-token-refreshed-0002')
        assert.strictEqual(client.getAuthSnapshot().authState, 'ready')
      })
    })
  })

  chain = chain.then(function () {
    return test('revoked session clears local credentials', function () {
      var storage = createMemoryStorage({
        sessionToken: 'revoked-token',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString()
      })
      var requestFn = createMockRequest(function (options) {
        var p = pathOf(options.url)
        if (p === '/api/v1/auth/refresh') {
          return fixtures.unauthorizedRevoked()
        }
        if (p === '/api/v1/me') {
          return fixtures.unauthorizedRevoked()
        }
        throw new Error('unexpected ' + p)
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      return client.request('/api/v1/me').then(
        function () {
          throw new Error('expected failure')
        },
        function (err) {
          assert.ok(err)
          assert.ok(err.code === 'SESSION_REVOKED' || err.code === 'SESSION_EXPIRED' || err.statusCode === 401)
          assert.strictEqual(storage.get('sessionToken'), '')
          assert.ok(
            client.getAuthSnapshot().authState === 'revoked' ||
              client.getAuthSnapshot().authState === 'expired' ||
              client.getAuthSnapshot().authState === 'unauthenticated'
          )
        }
      )
    })
  })

  chain = chain.then(function () {
    return test('network failure sets offline state', function () {
      var storage = createMemoryStorage({
        sessionToken: 'session-token-valid-0001',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString()
      })
      var requestFn = function () {
        return Promise.reject(fixtures.networkFail())
      }
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      return client.request('/api/v1/me').then(
        function () {
          throw new Error('expected offline error')
        },
        function (err) {
          assert.strictEqual(err.code, 'NETWORK_ERROR')
          assert.strictEqual(err.offline, true)
          assert.strictEqual(client.getAuthSnapshot().authState, 'offline')
          // local session retained for offline resume
          assert.strictEqual(client.getAuthSnapshot().hasSession, true)
        }
      )
    })
  })

  chain = chain.then(function () {
    return test('wechat login exchanges code and stores session', function () {
      var storage = createMemoryStorage({ apiBase: 'http://127.0.0.1:8000' })
      var requestFn = createMockRequest(function (options) {
        var p = pathOf(options.url)
        assert.ok(!options.header.Authorization, 'login must not send bearer')
        assert.strictEqual(p, '/api/v1/auth/wechat')
        assert.strictEqual(options.data.code, 'wx-code-1')
        return fixtures.ok(fixtures.validSession())
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      var auth = authApiModule.createAuthApi(client, {
        wxLogin: function () {
          return Promise.resolve('wx-code-1')
        },
        deviceLabel: function () {
          return 'test-device'
        }
      })
      return auth.loginWithWx().then(function (payload) {
        assert.strictEqual(payload.access_token, 'session-token-valid-0001')
        assert.strictEqual(client.getAuthSnapshot().authState, 'ready')
        assert.strictEqual(storage.get('sessionToken'), 'session-token-valid-0001')
        assert.strictEqual(client.getAuthSnapshot().owner.display_name, '学习者')
      })
    })
  })

  chain = chain.then(function () {
    return test('logout revokes remote session and clears local storage', function () {
      var storage = createMemoryStorage({
        sessionToken: 'session-token-valid-0001',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString(),
        ownerSummary: fixtures.OWNER
      })
      var requestFn = createMockRequest(function (options) {
        assert.strictEqual(pathOf(options.url), '/api/v1/auth/logout')
        assert.strictEqual(options.header.Authorization, 'Bearer session-token-valid-0001')
        return { statusCode: 204, data: '', header: {} }
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      var auth = authApiModule.createAuthApi(client, {
        wxLogin: function () {
          return Promise.resolve('x')
        }
      })
      return auth.logout().then(function (result) {
        assert.strictEqual(result.ok, true)
        assert.strictEqual(client.getAuthSnapshot().hasSession, false)
        assert.strictEqual(client.getAuthSnapshot().authState, 'unauthenticated')
        assert.strictEqual(storage.get('sessionToken'), '')
      })
    })
  })

  chain = chain.then(function () {
    return test('production environment hides dev token config', function () {
      var storage = createMemoryStorage({
        clientEnvironment: 'production',
        apiToken: 'should-not-be-used',
        sessionToken: ''
      })
      var client = httpModule.createHttpClient({
        storage: storage,
        request: createMockRequest(function () {
          return fixtures.ok({})
        })
      })
      client.setEnvironment('production')
      var snap = client.getAuthSnapshot()
      assert.strictEqual(snap.isDevConfigVisible, false)
      assert.strictEqual(client.getBearerToken(), '')
      // production clears stored dev token
      assert.strictEqual(storage.get('apiToken'), '')
    })
  })

  chain = chain.then(function () {
    return test('dev token still works in development without session', function () {
      var storage = createMemoryStorage({
        clientEnvironment: 'development',
        apiToken: 'dev-fixed-token',
        apiBase: 'http://127.0.0.1:8000'
      })
      var requestFn = createMockRequest(function (options) {
        assert.strictEqual(options.header.Authorization, 'Bearer dev-fixed-token')
        return fixtures.ok(fixtures.OWNER)
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      assert.strictEqual(client.getAuthSnapshot().authState, 'ready')
      return client.request('/api/v1/me').then(function (owner) {
        assert.strictEqual(owner.id, 1)
      })
    })
  })

  chain = chain.then(function () {
    return test('bootstrap with valid session fetches /me', function () {
      var storage = createMemoryStorage({
        sessionToken: 'session-token-valid-0001',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString()
      })
      var requestFn = createMockRequest(function (options) {
        assert.strictEqual(pathOf(options.url), '/api/v1/me')
        return fixtures.ok(fixtures.OWNER)
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      var auth = authApiModule.createAuthApi(client, {
        wxLogin: function () {
          throw new Error('should not login')
        }
      })
      return auth.bootstrap({ autoLogin: false }).then(function (result) {
        assert.strictEqual(result.authState, 'ready')
        assert.strictEqual(result.source, 'session')
        assert.strictEqual(result.owner.id, 1)
      })
    })
  })

  chain = chain.then(function () {
    return test('forbidden owner binding surfaces forbidden state', function () {
      var storage = createMemoryStorage({ apiBase: 'http://127.0.0.1:8000' })
      var requestFn = createMockRequest(function () {
        return fixtures.forbiddenOwner()
      })
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      var auth = authApiModule.createAuthApi(client, {
        wxLogin: function () {
          return Promise.resolve('code')
        }
      })
      return auth.loginWithWx().then(
        function () {
          throw new Error('expected forbidden')
        },
        function (err) {
          assert.strictEqual(err.code, 'OWNER_ALREADY_BOUND')
          assert.strictEqual(client.getAuthSnapshot().authState, 'forbidden')
        }
      )
    })
  })

  return chain.then(function () {
    console.log('')
    console.log(passed + ' passed, ' + failures + ' failed')
    if (failures > 0) {
      process.exit(1)
    }
  })
}

run().catch(function (err) {
  console.error(err)
  process.exit(1)
})
