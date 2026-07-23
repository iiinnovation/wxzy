#!/usr/bin/env node
'use strict'

var assert = require('assert')
var path = require('path')
var form = require(path.join(__dirname, '..', 'utils', 'profile-form.js'))
var profileApiModule = require(path.join(__dirname, '..', 'services', 'profile-api.js'))
var httpModule = require(path.join(__dirname, '..', 'services', 'http.js'))

var passed = 0
var failed = 0

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
          failed += 1
          console.error('not ok - ' + name)
          console.error('  ' + (err && err.stack ? err.stack : err))
        }
      )
    }
    passed += 1
    console.log('ok - ' + name)
    return Promise.resolve()
  } catch (err) {
    failed += 1
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
    }
  }
}

function run() {
  var chain = Promise.resolve()

  chain = chain.then(function () {
    return test('default form is valid and skippable optionals empty', function () {
      var state = form.defaultFormState()
      var validation = form.validateForm(state)
      assert.strictEqual(validation.ok, true)
      assert.strictEqual(validation.daily_minutes, 20)
      assert.ok(validation.study_days.every(Boolean))
      var maps = form.subjectMapsFromRows(state.subject_rows)
      assert.deepStrictEqual(maps.subject_priorities, {})
    })
  })

  chain = chain.then(function () {
    return test('profileToForm and buildUpdatePayload round-trip core fields', function () {
      var profile = {
        goal_type: 'exam',
        target_date: '2026-12-01',
        daily_minutes: 35,
        study_days: [true, true, true, true, true, false, false],
        desired_retention: 0.92,
        new_card_ceiling: 8,
        subject_priorities: { 方剂学: 5, 诊断学: 4 },
        initial_self_assessment: { 方剂学: 2, 诊断学: 3 },
        onboarding_completed_at: null,
        updated_at: '2026-07-23T00:00:00+00:00',
        display_name: '学习者',
        timezone: 'Asia/Shanghai'
      }
      var state = form.profileToForm(profile)
      assert.strictEqual(state.goal_type, 'exam')
      assert.strictEqual(state.custom_minutes, '35')
      assert.strictEqual(state.onboarding_completed, false)
      var enabled = state.subject_rows.filter(function (row) {
        return row.enabled
      })
      assert.ok(enabled.length >= 2)

      var payload = form.buildUpdatePayload(state, { completeOnboarding: true })
      assert.strictEqual(payload.goal_type, 'exam')
      assert.strictEqual(payload.daily_minutes, 35)
      assert.strictEqual(payload.target_date, '2026-12-01')
      assert.strictEqual(payload.onboarding_completed, true)
      assert.strictEqual(payload.subject_priorities['方剂学'], 5)
      assert.strictEqual(payload.expected_updated_at, profile.updated_at)
    })
  })

  chain = chain.then(function () {
    return test('validate rejects empty study days and out-of-range minutes', function () {
      var state = form.defaultFormState()
      state.study_days = [false, false, false, false, false, false, false]
      assert.strictEqual(form.validateForm(state).ok, false)
      state = form.defaultFormState()
      state.custom_minutes = '3'
      assert.strictEqual(form.validateForm(state).ok, false)
    })
  })

  chain = chain.then(function () {
    return test('summarize and onboarding complete flags', function () {
      var incomplete = form.summarizeProfile({
        goal_type: 'daily_learning',
        daily_minutes: 20,
        study_days: [true, true, true, true, true, true, true],
        subject_priorities: {},
        onboarding_completed_at: null
      })
      assert.strictEqual(incomplete.onboardingDone, false)
      assert.strictEqual(form.isOnboardingComplete({ onboarding_completed_at: null }), false)
      assert.strictEqual(
        form.isOnboardingComplete({ onboarding_completed_at: '2026-07-23T01:00:00Z' }),
        true
      )
    })
  })

  chain = chain.then(function () {
    return test('profile-api get and save use session bearer and concurrency token', function () {
      var storage = createMemoryStorage({
        apiBase: 'http://127.0.0.1:8000',
        sessionToken: 'session-profile-1',
        sessionExpiresAt: new Date(Date.now() + 3600 * 1000).toISOString()
      })
      var calls = []
      var requestFn = function (options) {
        calls.push(options)
        var path = options.url.replace(/^https?:\/\/[^/]+/, '')
        if (options.method === 'GET' && path === '/api/v1/me/learning-profile') {
          assert.strictEqual(options.header.Authorization, 'Bearer session-profile-1')
          return Promise.resolve({
            statusCode: 200,
            data: {
              id: 1,
              user_id: 1,
              goal_type: 'daily_learning',
              target_date: null,
              daily_minutes: 20,
              study_days: [true, true, true, true, true, true, true],
              desired_retention: 0.9,
              new_card_ceiling: 5,
              subject_priorities: {},
              initial_self_assessment: {},
              onboarding_completed_at: null,
              created_at: '2026-07-23T00:00:00+00:00',
              updated_at: '2026-07-23T00:00:00+00:00',
              display_name: null,
              timezone: 'Asia/Shanghai'
            },
            header: {}
          })
        }
        if (options.method === 'PUT' && path === '/api/v1/me/learning-profile') {
          assert.strictEqual(options.header.Authorization, 'Bearer session-profile-1')
          assert.strictEqual(options.data.expected_updated_at, '2026-07-23T00:00:00+00:00')
          assert.strictEqual(options.data.daily_minutes, 30)
          assert.strictEqual(options.data.onboarding_completed, true)
          return Promise.resolve({
            statusCode: 200,
            data: Object.assign({}, options.data, {
              id: 1,
              user_id: 1,
              onboarding_completed_at: '2026-07-23T01:00:00+00:00',
              updated_at: '2026-07-23T01:00:00+00:00',
              created_at: '2026-07-23T00:00:00+00:00'
            }),
            header: {}
          })
        }
        throw new Error('unexpected ' + options.method + ' ' + path)
      }
      var client = httpModule.createHttpClient({ storage: storage, request: requestFn })
      var api = profileApiModule.createProfileApi(client)
      return api.getLearningProfile().then(function (profile) {
        var state = form.profileToForm(profile)
        state.daily_minutes = 30
        state.custom_minutes = ''
        return api.saveForm(state, { completeOnboarding: true }).then(function (saved) {
          assert.strictEqual(saved.daily_minutes, 30)
          assert.ok(saved.onboarding_completed_at)
          assert.strictEqual(calls.length, 2)
        })
      })
    })
  })

  chain = chain.then(function () {
    return test('pages do not assemble Authorization headers', function () {
      var fs = require('fs')
      var root = path.join(__dirname, '..', 'pages')
      var offenders = []
      function walk(dir) {
        fs.readdirSync(dir).forEach(function (name) {
          var full = path.join(dir, name)
          if (fs.statSync(full).isDirectory()) {
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
      assert.deepStrictEqual(offenders, [])
    })
  })

  return chain.then(function () {
    console.log('')
    console.log(passed + ' passed, ' + failed + ' failed')
    if (failed > 0) process.exit(1)
  })
}

run().catch(function (err) {
  console.error(err)
  process.exit(1)
})
