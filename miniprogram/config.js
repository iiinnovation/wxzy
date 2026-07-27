const DEVELOPMENT_CONFIG = {
  environment: 'development',
  defaultApiBase: 'http://127.0.0.1:8000',
  autoWeChatLogin: false
}

const PRODUCTION_CONFIG = {
  environment: 'production',
  defaultApiBase: 'https://api.luoandlt.xin',
  autoWeChatLogin: true
}

function forEnvVersion(envVersion) {
  return envVersion === 'trial' || envVersion === 'release'
    ? PRODUCTION_CONFIG
    : DEVELOPMENT_CONFIG
}

function currentEnvVersion() {
  try {
    if (typeof wx !== 'undefined' && wx.getAccountInfoSync) {
      const account = wx.getAccountInfoSync()
      return account && account.miniProgram && account.miniProgram.envVersion
    }
  } catch (e) {
    // Static tooling outside WeChat should validate the production defaults.
  }
  return 'release'
}

module.exports = Object.assign({}, forEnvVersion(currentEnvVersion()), {
  forEnvVersion: forEnvVersion
})
