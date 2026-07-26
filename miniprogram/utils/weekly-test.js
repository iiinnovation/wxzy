'use strict'

function summarizeWeeklyPlan(plan) {
  const items = (plan && plan.items) || []
  const pending = items.filter(function (item) {
    return item.status === 'pending'
  })
  const mixedPending = pending.filter(function (item) {
    return item.item_type === 'mixed_weekly'
  })
  const mixedCompleted = items.filter(function (item) {
    return item.item_type === 'mixed_weekly' && item.status === 'completed'
  })
  const firstMixedIndex = pending.findIndex(function (item) {
    return item.item_type === 'mixed_weekly'
  })
  const state = mixedPending.length
    ? firstMixedIndex === 0
      ? 'ready'
      : 'blocked'
    : mixedCompleted.length
      ? 'completed'
      : 'empty'
  return {
    state: state,
    mixedPendingCount: mixedPending.length,
    mixedCompletedCount: mixedCompleted.length,
    pendingBeforeCount: firstMixedIndex > 0 ? firstMixedIndex : 0
  }
}

module.exports = {
  summarizeWeeklyPlan: summarizeWeeklyPlan
}
