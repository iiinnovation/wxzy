function getAppSafe() {
  try {
    return getApp()
  } catch (e) {
    return null
  }
}

function getConfig() {
  const app = getAppSafe()
  const apiBase = (app && app.globalData.apiBase) || wx.getStorageSync('apiBase') || 'http://127.0.0.1:8000'
  const token = (app && app.globalData.token) || wx.getStorageSync('apiToken') || ''
  return { apiBase: String(apiBase).replace(/\/$/, ''), token }
}

function request(path, options = {}) {
  const { apiBase, token } = getConfig()
  const method = options.method || 'GET'
  const data = options.data
  return new Promise((resolve, reject) => {
    wx.request({
      url: apiBase + path,
      method,
      data,
      timeout: options.timeout || 15000,
      header: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/json',
        ...(options.header || {})
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        if (res.statusCode === 401) {
          reject(new Error('连接凭证无效，请在“我的”中重新设置'))
          return
        }
        const detail = (res.data && (res.data.detail || res.data.message)) || ('HTTP ' + res.statusCode)
        reject(new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)))
      },
      fail(err) {
        reject(new Error((err && err.errMsg) || 'network error'))
      }
    })
  })
}

function getHealth() {
  return request('/health')
}

function getStats() {
  return request('/stats/summary')
}

function getBooks() {
  return request('/books')
}

function getCards(params = {}) {
  const q = []
  if (params.book_id != null) q.push('book_id=' + params.book_id)
  if (params.q) q.push('q=' + encodeURIComponent(params.q))
  if (params.limit) q.push('limit=' + params.limit)
  const qs = q.length ? ('?' + q.join('&')) : ''
  return request('/cards' + qs)
}

function getDue(limit = 30) {
  return request('/review/due?limit=' + limit)
}

function postAnswer(cardId, rating) {
  return request('/review/answer', {
    method: 'POST',
    data: { card_id: cardId, rating }
  })
}

function saveConfig({ apiBase, token }) {
  if (apiBase != null) {
    wx.setStorageSync('apiBase', apiBase)
    const app = getAppSafe()
    if (app) app.globalData.apiBase = apiBase
  }
  if (token != null) {
    wx.setStorageSync('apiToken', token)
    const app = getAppSafe()
    if (app) app.globalData.token = token
  }
}

module.exports = {
  getConfig,
  getHealth,
  getStats,
  getBooks,
  getCards,
  getDue,
  postAnswer,
  saveConfig
}
