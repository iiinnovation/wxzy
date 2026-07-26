'use strict'

Component({
  properties: {
    type: { type: String, value: 'empty' },
    title: { type: String, value: '' },
    message: { type: String, value: '' },
    actionLabel: { type: String, value: '' }
  },
  methods: {
    onAction: function () {
      this.triggerEvent('action')
    }
  }
})
