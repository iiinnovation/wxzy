'use strict'

const withQuery = require('./http').withQuery

function createInsightsApi(httpClient) {
  if (!httpClient || typeof httpClient.request !== 'function') {
    throw new Error('insights api requires an http client')
  }
  return {
    getSummary: function () {
      return httpClient.request('/api/v1/insights/summary')
    },
    getWorkload: function () {
      return httpClient.request('/api/v1/insights/workload')
    },
    getWeakTopics: function (params) {
      params = params || {}
      return httpClient.request(
        withQuery('/api/v1/insights/weak-topics', {
          offset: Number(params.offset || 0),
          limit: Number(params.limit || 20)
        })
      )
    }
  }
}

let defaultApi = null

function getDefaultInsightsApi() {
  if (!defaultApi) {
    defaultApi = createInsightsApi(require('./http').getDefaultClient())
  }
  return defaultApi
}

module.exports = {
  createInsightsApi: createInsightsApi,
  getDefaultInsightsApi: getDefaultInsightsApi
}
