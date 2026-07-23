/**
 * Domain API helpers used by current pages.
 * Authorization is owned by services/http.js — pages never set auth headers.
 */

'use strict'

var httpModule = require('./http')
var authApiModule = require('./auth-api')
var profileApiModule = require('./profile-api')
var formHelpers = require('../utils/profile-form')

function client() {
  return httpModule.getDefaultClient()
}

function authApi() {
  return authApiModule.getDefaultAuthApi()
}

function profileApi() {
  return profileApiModule.getDefaultProfileApi()
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
  return request('/stats/summary')
}

function getBooks() {
  return request('/books')
}

function getCards(params) {
  params = params || {}
  var q = []
  if (params.book_id != null) q.push('book_id=' + params.book_id)
  if (params.q) q.push('q=' + encodeURIComponent(params.q))
  if (params.limit) q.push('limit=' + params.limit)
  var qs = q.length ? '?' + q.join('&') : ''
  return request('/cards' + qs)
}

function getDue(limit) {
  return request('/review/due?limit=' + (limit || 30))
}

function postAnswer(cardId, rating) {
  return request('/review/answer', {
    method: 'POST',
    data: { card_id: cardId, rating: rating }
  })
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
  getBooks: getBooks,
  getCards: getCards,
  getDue: getDue,
  postAnswer: postAnswer,
  saveConfig: saveConfig,
  request: request,
  loginWithWx: loginWithWx,
  logout: logout,
  bootstrapAuth: bootstrapAuth,
  fetchMe: fetchMe,
  getLearningProfile: getLearningProfile,
  updateLearningProfile: updateLearningProfile,
  saveLearningProfileForm: saveLearningProfileForm,
  summarizeProfile: summarizeProfile,
  isOnboardingComplete: isOnboardingComplete
}
