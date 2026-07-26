'use strict'
Component({properties:{value:{type:Number,value:0},total:{type:Number,value:0},label:{type:String,value:''}},observers:{'value,total':function(value,total){const percent=total?Math.max(0,Math.min(100,Math.round(value/total*100))):0;this.setData({percent:percent})}},data:{percent:0}})
