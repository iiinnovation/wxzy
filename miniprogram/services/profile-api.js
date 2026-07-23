/**
 * Learning profile API helpers.
 * Authorization is owned by services/http.js.
 */
'use strict'

var httpModule = require('./http')
var formHelpers = require('../utils/profile-form')

function createProfileApi(client) {
  client = client || httpModule.getDefaultClient()

  function getLearningProfile() {
    return client.request('/api/v1/me/learning-profile', {
      method: 'GET',
      auth: true
    })
  }

  function updateLearningProfile(payload) {
    return client.request('/api/v1/me/learning-profile', {
      method: 'PUT',
      auth: true,
      data: payload
    })
  }

  function saveForm(form, options) {
    var payload = formHelpers.buildUpdatePayload(form, options)
    return updateLearningProfile(payload)
  }

  return {
    getLearningProfile: getLearningProfile,
    updateLearningProfile: updateLearningProfile,
    saveForm: saveForm
  }
}

var defaultApi = null

function getDefaultProfileApi() {
  if (!defaultApi) {
    defaultApi = createProfileApi()
  }
  return defaultApi
}

function resetDefaultProfileApiForTests(api) {
  defaultApi = api || null
}

module.exports = {
  createProfileApi: createProfileApi,
  getDefaultProfileApi: getDefaultProfileApi,
  resetDefaultProfileApiForTests: resetDefaultProfileApiForTests
}
