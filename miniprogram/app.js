App({
  globalData: {
    apiBase: '',
    token: ''
  },
  onLaunch() {
    // Keep credentials out of the package; configure them on the Me page.
    const apiBase = wx.getStorageSync('apiBase') || 'http://127.0.0.1:8000'
    const token = wx.getStorageSync('apiToken') || ''
    this.globalData.apiBase = apiBase
    this.globalData.token = token
  }
})
