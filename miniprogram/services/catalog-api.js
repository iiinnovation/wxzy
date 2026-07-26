'use strict'

const withQuery = require('./http').withQuery

function createCatalogApi(httpClient) {
  if (!httpClient || typeof httpClient.request !== 'function') {
    throw new Error('catalog api requires an http client')
  }

  return {
    listBooks: function () {
      return httpClient.request('/api/v1/catalog/books')
    },
    listChapters: function (bookId) {
      return httpClient.request('/api/v1/catalog/books/' + Number(bookId) + '/chapters')
    },
    searchCards: function (params) {
      return httpClient.request(withQuery('/api/v1/catalog/cards', params || {}))
    },
    getCard: function (cardId) {
      return httpClient.request('/api/v1/catalog/cards/' + Number(cardId))
    },
    listCardSources: function (cardId) {
      return httpClient.request('/api/v1/catalog/cards/' + Number(cardId) + '/sources')
    }
  }
}

let defaultApi = null

function getDefaultCatalogApi() {
  if (!defaultApi) {
    defaultApi = createCatalogApi(require('./http').getDefaultClient())
  }
  return defaultApi
}

module.exports = {
  createCatalogApi: createCatalogApi,
  getDefaultCatalogApi: getDefaultCatalogApi
}
