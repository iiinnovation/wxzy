#!/usr/bin/env node
'use strict'

const assert = require('assert')
const path = require('path')
const httpModule = require(path.join(__dirname, '..', 'services', 'http.js'))
const catalogModule = require(path.join(__dirname, '..', 'services', 'catalog-api.js'))
const learningModule = require(path.join(__dirname, '..', 'services', 'learning-api.js'))
const insightsModule = require(path.join(__dirname, '..', 'services', 'insights-api.js'))

let passed = 0
let failed = 0

function test(name, fn) {
  return Promise.resolve().then(fn).then(function () {
    passed += 1
    console.log('ok - ' + name)
  }, function (err) {
    failed += 1
    console.error('not ok - ' + name)
    console.error('  ' + (err && err.stack ? err.stack : err))
  })
}

function storage(seed) {
  const values = Object.assign({}, seed || {})
  return {
    get: function (key) { return values[key] || '' },
    set: function (key, value) { values[key] = value },
    remove: function (key) { delete values[key] }
  }
}

function pathOf(url) {
  return url.replace(/^https?:\/\/[^/]+/, '')
}

function clientWith(handler) {
  return httpModule.createHttpClient({
    storage: storage({
      apiBase: 'http://127.0.0.1:8000',
      sessionToken: 'session-p7',
      sessionExpiresAt: new Date(Date.now() + 3600000).toISOString()
    }),
    idFactory: function () { return 'req-p7-fixture' },
    request: function (options) { return Promise.resolve().then(function () { return handler(options) }) }
  })
}

function ok(data) {
  return { statusCode: 200, data: data || {}, header: {} }
}

function run() {
  let chain = Promise.resolve()

  chain = chain.then(function () {
    return test('domain clients use v1 routes and centralized auth/request id', function () {
      const calls = []
      const client = clientWith(function (options) {
        calls.push(options)
        return ok({})
      })
      const catalog = catalogModule.createCatalogApi(client)
      const learning = learningModule.createLearningApi(client)
      const insights = insightsModule.createInsightsApi(client)
      return Promise.all([
        catalog.listBooks(),
        catalog.listChapters(7),
        catalog.searchCards({ book_id: 7, q: '桂枝 汤', limit: 20 }),
        learning.getToday(),
        learning.adjustTodayBudget(30),
        learning.getNextTask(9),
        learning.updateChapterEnrollments(7, 'suspended'),
        insights.getSummary(),
        insights.getWorkload(),
        insights.getWeakTopics({ offset: 20, limit: 10 })
      ]).then(function () {
        const paths = calls.map(function (call) { return pathOf(call.url) })
        assert.ok(paths.indexOf('/api/v1/catalog/books') >= 0)
        assert.ok(paths.indexOf('/api/v1/catalog/books/7/chapters') >= 0)
        assert.ok(paths.indexOf('/api/v1/learning/today') >= 0)
        assert.ok(paths.indexOf('/api/v1/chapters/7/enrollments') >= 0)
        assert.ok(paths.indexOf('/api/v1/insights/summary') >= 0)
        assert.ok(paths.indexOf('/api/v1/insights/weak-topics?offset=20&limit=10') >= 0)
        assert.ok(paths.some(function (value) { return value.indexOf('q=%E6%A1%82%E6%9E%9D%20%E6%B1%A4') >= 0 }))
        calls.forEach(function (call) {
          assert.strictEqual(call.header.Authorization, 'Bearer session-p7')
          assert.strictEqual(call.header['X-Request-Id'], 'req-p7-fixture')
        })
      })
    })
  })

  chain = chain.then(function () {
    return test('timeout is classified and retriable', function () {
      const client = clientWith(function () {
        const error = new Error('request:fail timeout')
        error.errMsg = 'request:fail timeout'
        throw error
      })
      return client.request('/api/v1/learning/today').then(function () {
        throw new Error('expected timeout')
      }, function (err) {
        assert.strictEqual(err.code, 'REQUEST_TIMEOUT')
        assert.strictEqual(err.retriable, true)
        assert.ok(err.message.indexOf('超时') >= 0)
      })
    })
  })

  chain = chain.then(function () {
    return test('business conflict uses safe actionable copy', function () {
      const client = clientWith(function () {
        return {
          statusCode: 409,
          data: {
            code: 'REVIEW_ATTEMPT_CONFLICT',
            message: 'internal current-state mismatch',
            request_id: 'req-conflict'
          },
          header: {}
        }
      })
      return client.request('/api/v1/review-attempts', { method: 'POST', data: {} }).then(function () {
        throw new Error('expected conflict')
      }, function (err) {
        assert.strictEqual(err.code, 'REVIEW_ATTEMPT_CONFLICT')
        assert.strictEqual(err.requestId, 'req-conflict')
        assert.strictEqual(err.message, '这张卡的学习记录已更新，请重新加载后继续')
      })
    })
  })

  chain = chain.then(function () {
    return test('learning writes preserve payload and generate bounded client attempt id', function () {
      let captured = null
      const client = clientWith(function (options) {
        captured = options
        return ok({ id: 1, replayed: false })
      })
      const learning = learningModule.createLearningApi(client, {
        now: function () { return 123456789 },
        random: function () { return 0.5 }
      })
      const attemptId = learning.createClientAttemptId(3, 8)
      assert.ok(/^mp-3-8-/.test(attemptId))
      assert.ok(attemptId.length < 128)
      return learning.submitReviewAttempt({
        session_id: 3,
        card_id: 8,
        card_revision: 2,
        client_attempt_id: attemptId,
        rating: 3,
        response_ms: 900
      }).then(function () {
        assert.strictEqual(pathOf(captured.url), '/api/v1/review-attempts')
        assert.strictEqual(captured.method, 'POST')
        assert.strictEqual(captured.data.client_attempt_id, attemptId)
        assert.strictEqual(captured.data.rating, 3)
      })
    })
  })

  return chain.then(function () {
    console.log('')
    console.log(passed + ' passed, ' + failed + ' failed')
    if (failed) process.exit(1)
  })
}

run().catch(function (err) {
  console.error(err)
  process.exit(1)
})
