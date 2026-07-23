/**
 * Client build configuration.
 * Release builds should set environment to "production" so the Me page
 * never offers a manual API Token field.
 */
module.exports = {
  environment: 'development',
  defaultApiBase: 'http://127.0.0.1:8000',
  /**
   * When true and no local session/dev token exists, app boot calls wx.login.
   * Keep false for local simulator work against AUTH_MODE=dev_token.
   */
  autoWeChatLogin: false
}
