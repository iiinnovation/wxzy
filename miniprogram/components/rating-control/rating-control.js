'use strict'
Component({properties:{disabled:{type:Boolean,value:false}},methods:{onRate:function(e){if(this.properties.disabled)return;this.triggerEvent('rate',{rating:Number(e.currentTarget.dataset.rating)})}}})
