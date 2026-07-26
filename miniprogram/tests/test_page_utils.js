#!/usr/bin/env node
'use strict'

const assert = require('assert')
const requestUtils = require('../utils/page-request')
const format = require('../utils/format')
const weekly = require('../utils/weekly-test')
const repairDisplay = require('../utils/repair-display')

const guard = requestUtils.createPageRequestGuard()
const first = guard.begin()
assert.strictEqual(guard.isCurrent(first), true)
const second = guard.begin()
assert.strictEqual(guard.isCurrent(first), false)
assert.strictEqual(guard.isCurrent(second), true)
guard.dispose()
assert.strictEqual(guard.isCurrent(second), false)

const auth = requestUtils.errorView({ code: 'SESSION_EXPIRED', message: 'expired' })
assert.strictEqual(auth.unauthorized, true)
assert.strictEqual(requestUtils.canRetrySameWrite({ retriable: true }), true)
assert.strictEqual(requestUtils.canRetrySameWrite({ statusCode: 409, retriable: false }), false)
assert.strictEqual(format.percent(3, 4), 75)
assert.strictEqual(format.itemTypeLabel('repair'), '修复练习')
assert.strictEqual(format.localDateLabel('2026-07-26'), '7月26日')
assert.ok(/^2026-07-26 /.test(format.dateTimeLabel('2026-07-26T08:30:00+08:00')))

assert.strictEqual(weekly.summarizeWeeklyPlan({ items: [] }).state, 'empty')
assert.strictEqual(
  weekly.summarizeWeeklyPlan({
    items: [{ item_type: 'mixed_weekly', status: 'completed' }]
  }).state,
  'completed'
)
assert.deepStrictEqual(
  weekly.summarizeWeeklyPlan({
    items: [
      { item_type: 'due', status: 'pending' },
      { item_type: 'mixed_weekly', status: 'pending' }
    ]
  }),
  { state: 'blocked', mixedPendingCount: 1, mixedCompletedCount: 0, pendingBeforeCount: 1 }
)
assert.strictEqual(
  weekly.summarizeWeeklyPlan({
    items: [{ item_type: 'mixed_weekly', status: 'pending' }]
  }).state,
  'ready'
)
const repair = repairDisplay.decorateRepairSuggestion({
  source: { chapter: '伤寒', section: '辨证' },
  signals: [{ code: 'repeated_again', detail: 'again_count=3' }],
  actions: [{ code: 'reread_source', reason: 'internal text' }]
})
assert.strictEqual(repair.firstSignalLabel, '近 30 天多次选择“重来”')
assert.strictEqual(repair.firstActionLabel, '先重读来源片段再进行回忆')
assert.strictEqual(repair.source.chapter_label, '伤寒 / 辨证')

const http = require('../services/http')
assert.strictEqual(http.withQuery('/x', { a: 1, b: '', c: null, d: 'y z' }), '/x?a=1&d=y%20z')
assert.strictEqual(http.withQuery('/x', {}), '/x')

const authorizedEvents = []
const gReady = requestUtils.createPageRequestGuard()
const readyRun = requestUtils
  .loadWithAuth(gReady, {
    authorized: function () {
      return true
    },
    fetch: function (isCurrent) {
      authorizedEvents.push('fetch:' + isCurrent())
      return Promise.resolve('data')
    },
    onReady: function (value) {
      authorizedEvents.push('ready:' + value)
    },
    onError: function () {
      authorizedEvents.push('error')
    }
  })
  .then(function () {
    assert.deepStrictEqual(authorizedEvents, ['fetch:true', 'ready:data'])
  })

const unauthorizedEvents = []
const gUnauthorized = requestUtils.createPageRequestGuard()
const unauthorizedRun = requestUtils
  .loadWithAuth(gUnauthorized, {
    authorized: function () {
      return false
    },
    onUnauthorized: function () {
      unauthorizedEvents.push('unauthorized')
    },
    fetch: function () {
      unauthorizedEvents.push('fetch')
      return Promise.resolve('x')
    },
    onReady: function () {
      unauthorizedEvents.push('ready')
    },
    onError: function () {
      unauthorizedEvents.push('error')
    }
  })
  .then(function () {
    assert.deepStrictEqual(unauthorizedEvents, ['unauthorized'])
  })

const errorEvents = []
const gError = requestUtils.createPageRequestGuard()
const errorRun = requestUtils
  .loadWithAuth(gError, {
    fetch: function () {
      return Promise.reject({ code: 'SESSION_EXPIRED', message: 'expired' })
    },
    onReady: function () {
      errorEvents.push('ready')
    },
    onError: function (view) {
      errorEvents.push('error:' + view.unauthorized)
    }
  })
  .then(function () {
    assert.deepStrictEqual(errorEvents, ['error:true'])
  })

const staleEvents = []
const gStale = requestUtils.createPageRequestGuard()
const staleRun = requestUtils.loadWithAuth(gStale, {
  fetch: function () {
    return new Promise(function (resolve) {
      setTimeout(function () {
        resolve('late')
      }, 5)
    })
  },
  onReady: function () {
    staleEvents.push('ready')
  },
  onError: function () {
    staleEvents.push('error')
  }
})
gStale.dispose()
const staleChecked = staleRun.then(function () {
  assert.deepStrictEqual(staleEvents, [])
})

Promise.all([readyRun, unauthorizedRun, errorRun, staleChecked])
  .then(function () {
    console.log('20 passed, 0 failed')
  })
  .catch(function (error) {
    console.error(error)
    console.log('tests failed')
    process.exit(1)
  })
