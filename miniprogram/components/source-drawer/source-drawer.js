'use strict'

Component({
  properties: {
    open: { type: Boolean, value: false },
    loading: { type: Boolean, value: false },
    error: { type: String, value: '' },
    sources: { type: Array, value: [] }
  },
  methods: {
    onClose: function () {
      this.triggerEvent('close')
    },
    onRetry: function () {
      this.triggerEvent('retry')
    },
    stop: function () {}
  }
})
