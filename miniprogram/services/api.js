/**
 * Domain API helpers used by current pages.
 * Authorization is owned by services/http.js — pages never set auth headers.
 */

'use strict'

const httpModule = require('./http')
const authApiModule = require('./auth-api')
const profileApiModule = require('./profile-api')
const catalogApiModule = require('./catalog-api')
const learningApiModule = require('./learning-api')
const insightsApiModule = require('./insights-api')
const formHelpers = require('../utils/profile-form')

function client() {
  return httpModule.getDefaultClient()
}

function authApi() {
  return authApiModule.getDefaultAuthApi()
}

function profileApi() {
  return profileApiModule.getDefaultProfileApi()
}

function catalogApi() {
  return catalogApiModule.getDefaultCatalogApi()
}

function learningApi() {
  return learningApiModule.getDefaultLearningApi()
}

function insightsApi() {
  return insightsApiModule.getDefaultInsightsApi()
}

function getConfig() {
  return client().getConfig()
}

function getAuthSnapshot() {
  return client().getAuthSnapshot()
}

function saveConfig(config) {
  return client().saveConfig(config)
}

function request(path, options) {
  return client().request(path, options)
}

function getHealth() {
  return request('/health', { auth: false, retryOnUnauthorized: false })
}

function getStats() {
  return request('/api/v1/stats/summary')
}

function loginWithWx() {
  return authApi().loginWithWx()
}

function logout() {
  return authApi().logout()
}

function bootstrapAuth(options) {
  return authApi().bootstrap(options)
}

function fetchMe() {
  return authApi().fetchMe()
}

function listSessions() {
  return authApi().listSessions()
}

function revokeSession(sessionId) {
  return authApi().revokeSession(sessionId)
}

function exportOwnerData() {
  return authApi().exportData()
}

function deleteOwnerData() {
  return authApi().deleteData()
}

function getLearningProfile() {
  return profileApi().getLearningProfile()
}

function updateLearningProfile(payload) {
  return profileApi().updateLearningProfile(payload)
}

function saveLearningProfileForm(form, options) {
  return profileApi().saveForm(form, options)
}

function summarizeProfile(profile) {
  return formHelpers.summarizeProfile(profile)
}

function isOnboardingComplete(profile) {
  return formHelpers.isOnboardingComplete(profile)
}

module.exports = {
  getConfig: getConfig,
  getAuthSnapshot: getAuthSnapshot,
  getHealth: getHealth,
  getStats: getStats,
  saveConfig: saveConfig,
  request: request,
  loginWithWx: loginWithWx,
  logout: logout,
  bootstrapAuth: bootstrapAuth,
  fetchMe: fetchMe,
  listSessions: listSessions,
  revokeSession: revokeSession,
  exportOwnerData: exportOwnerData,
  deleteOwnerData: deleteOwnerData,
  getLearningProfile: getLearningProfile,
  updateLearningProfile: updateLearningProfile,
  saveLearningProfileForm: saveLearningProfileForm,
  summarizeProfile: summarizeProfile,
  isOnboardingComplete: isOnboardingComplete,
  catalog: catalogApi,
  learning: learningApi,
  insights: insightsApi
}
