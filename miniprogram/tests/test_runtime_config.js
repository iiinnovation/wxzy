'use strict'

const assert = require('assert')
const config = require('../config')

const development = config.forEnvVersion('develop')
assert.strictEqual(development.environment, 'development')
assert.strictEqual(development.defaultApiBase, 'http://127.0.0.1:8000')
assert.strictEqual(development.autoWeChatLogin, false)

const trial = config.forEnvVersion('trial')
assert.strictEqual(trial.environment, 'production')
assert.strictEqual(trial.defaultApiBase, 'https://api.luoandlt.xin')
assert.strictEqual(trial.autoWeChatLogin, true)

const release = config.forEnvVersion('release')
assert.deepStrictEqual(release, trial)

console.log('3 passed, 0 failed')
