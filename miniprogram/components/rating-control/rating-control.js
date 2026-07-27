'use strict'
Component({properties:{disabled:{type:Boolean,value:false},recommendedRating:{type:Number,value:0}},methods:{onRate:function(e){if(this.properties.disabled)return;this.triggerEvent('rate',{rating:Number(e.currentTarget.dataset.rating)})}}})
