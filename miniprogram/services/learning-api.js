'use strict'

const withQuery = require('./http').withQuery

function createLearningApi(httpClient, deps) {
  if (!httpClient || typeof httpClient.request !== 'function') {
    throw new Error('learning api requires an http client')
  }
  deps = deps || {}
  const now = deps.now || Date.now
  const random = deps.random || Math.random

  function request(path, method, data, options) {
    options = options || {}
    return httpClient.request(path, {
      method: method,
      data: data,
      timeout: options.timeout,
      requestId: options.requestId,
      retryOnUnauthorized: options.retryOnUnauthorized
    })
  }

  function createClientAttemptId(sessionId, cardId) {
    return [
      'mp',
      Number(sessionId),
      Number(cardId),
      Number(now()).toString(36),
      Math.floor(random() * 0x1000000).toString(36)
    ].join('-')
  }

  return {
    getToday: function () {
      return request('/api/v1/learning/today', 'GET')
    },
    adjustTodayBudget: function (budgetMinutes) {
      return request('/api/v1/learning/today', 'PUT', {
        budget_minutes: Number(budgetMinutes)
      })
    },
    createStudySession: function (dailyPlanId, options) {
      options = options || {}
      return request('/api/v1/study-sessions', 'POST', {
        daily_plan_id: Number(dailyPlanId),
        auto_start: options.autoStart !== false
      })
    },
    getNextTask: function (sessionId) {
      return request('/api/v1/study-sessions/' + Number(sessionId) + '/next', 'GET')
    },
    completeSession: function (sessionId) {
      return request('/api/v1/study-sessions/' + Number(sessionId) + '/complete', 'POST')
    },
    interruptSession: function (sessionId, reason) {
      return request('/api/v1/study-sessions/' + Number(sessionId) + '/interrupt', 'POST', {
        reason: String(reason || '用户暂时离开')
      })
    },
    resumeSession: function (sessionId) {
      return request('/api/v1/study-sessions/' + Number(sessionId) + '/resume', 'POST')
    },
    submitReviewAttempt: function (payload, options) {
      payload = Object.assign({}, payload || {})
      if (!payload.client_attempt_id) {
        payload.client_attempt_id = createClientAttemptId(payload.session_id, payload.card_id)
      }
      return request('/api/v1/review-attempts', 'POST', payload, options)
    },
    enroll: function (payload) {
      return request('/api/v1/enrollments', 'POST', payload)
    },
    updateEnrollment: function (enrollmentId, status) {
      return request('/api/v1/enrollments/' + Number(enrollmentId), 'PUT', {
        status: status
      })
    },
    updateChapterEnrollments: function (chapterId, status) {
      return request('/api/v1/chapters/' + Number(chapterId) + '/enrollments', 'PUT', {
        status: status
      })
    },
    getRepairSuggestions: function (limit) {
      return request(
        withQuery('/api/v1/learning/repair-suggestions', { limit: Number(limit || 20) }),
        'GET'
      )
    },
    createClientAttemptId: createClientAttemptId
  }
}

let defaultApi = null

function getDefaultLearningApi() {
  if (!defaultApi) {
    defaultApi = createLearningApi(require('./http').getDefaultClient())
  }
  return defaultApi
}

module.exports = {
  createLearningApi: createLearningApi,
  getDefaultLearningApi: getDefaultLearningApi
}
