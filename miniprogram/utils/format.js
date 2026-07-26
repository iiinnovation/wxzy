'use strict'

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value) || 0))
}

function percent(value, total) {
  if (!total) return 0
  return Math.round(clamp(value / total, 0, 1) * 100)
}

function localDateLabel(value) {
  const text = String(value || '')
  const parts = text.slice(0, 10).split('-')
  if (parts.length !== 3) return text
  return Number(parts[1]) + '月' + Number(parts[2]) + '日'
}

function dateTimeLabel(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return String(value || '')
  function pad(part) {
    return part < 10 ? '0' + part : String(part)
  }
  return [
    date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate()),
    pad(date.getHours()) + ':' + pad(date.getMinutes())
  ].join(' ')
}

function itemTypeLabel(value) {
  const labels = {
    due: '到期复习',
    overdue: '逾期复习',
    new: '新内容',
    weak_topic: '薄弱练习',
    repair: '修复练习',
    mixed_weekly: '周度混合'
  }
  return labels[value] || '学习任务'
}

module.exports = {
  clamp: clamp,
  percent: percent,
  localDateLabel: localDateLabel,
  dateTimeLabel: dateTimeLabel,
  itemTypeLabel: itemTypeLabel
}
