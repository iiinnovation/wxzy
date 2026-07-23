'use strict'

var OWNER = {
  id: 1,
  status: 'active',
  display_name: '学习者',
  timezone: 'Asia/Shanghai'
}

function sessionPayload(token, expiresAt) {
  return {
    access_token: token,
    token_type: 'bearer',
    expires_at: expiresAt || new Date(Date.now() + 3600 * 1000).toISOString(),
    owner: OWNER
  }
}

function errorBody(code, message, status) {
  return {
    statusCode: status || 400,
    data: {
      code: code,
      message: message,
      request_id: 'req_fixture',
      details: null
    },
    header: { 'X-Request-Id': 'req_fixture' }
  }
}

function ok(data, statusCode) {
  return {
    statusCode: statusCode == null ? 200 : statusCode,
    data: data,
    header: { 'X-Request-Id': 'req_ok' }
  }
}

module.exports = {
  OWNER: OWNER,
  sessionPayload: sessionPayload,
  errorBody: errorBody,
  ok: ok,
  validSession: function () {
    return sessionPayload('session-token-valid-0001', new Date(Date.now() + 7200 * 1000).toISOString())
  },
  refreshedSession: function () {
    return sessionPayload('session-token-refreshed-0002', new Date(Date.now() + 7200 * 1000).toISOString())
  },
  expiredSession: function () {
    return sessionPayload('session-token-expired-0003', new Date(Date.now() - 60 * 1000).toISOString())
  },
  unauthorizedExpired: function () {
    return errorBody('SESSION_EXPIRED', '登录已过期，请重新登录', 401)
  },
  unauthorizedRevoked: function () {
    return errorBody('SESSION_REVOKED', '登录已失效，请重新登录', 401)
  },
  forbiddenOwner: function () {
    return errorBody('OWNER_ALREADY_BOUND', '此学习账户已绑定其他微信身份', 403)
  },
  networkFail: function () {
    var err = new Error('request:fail')
    err.errMsg = 'request:fail'
    return err
  }
}
