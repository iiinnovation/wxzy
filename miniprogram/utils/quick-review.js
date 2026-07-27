'use strict'

const FAST_RECALL_MS = 20000

function decorateAnswerPoints(values) {
  if (!Array.isArray(values)) return []
  return values.reduce(function (points, value) {
    const text = String(value || '').trim()
    if (!text) return points
    points.push({ index: points.length, text: text, checked: false })
    return points
  }, [])
}

function setCheckedAnswerPoints(points, selectedIndexes) {
  const selected = {}
  const indexes = selectedIndexes || []
  indexes.forEach(function (value) {
    selected[Number(value)] = true
  })
  return (points || []).map(function (point) {
    return Object.assign({}, point, { checked: Boolean(selected[point.index]) })
  })
}

function countRecalledPoints(points) {
  return (points || []).reduce(function (count, point) {
    return count + (point.checked ? 1 : 0)
  }, 0)
}

function recommendRating(points, touched, recallMs) {
  if (!touched || !points || !points.length) return 0
  const recalled = countRecalledPoints(points)
  if (!recalled) return 1
  if (recalled < points.length) return 2
  if (Number.isFinite(recallMs) && recallMs <= FAST_RECALL_MS) return 4
  return 3
}

function buildAnswerPayload(options) {
  const values = options || {}
  const points = values.points || []
  const answer = String(values.writtenAnswer || '').trim()
  const payload = {
    recall_mode: values.recallMode === 'writing' ? 'writing' : 'quick'
  }
  if (Number.isFinite(values.recallMs)) {
    payload.recall_ms = Math.max(0, Math.round(values.recallMs))
  }
  if (answer) payload.written_answer = answer
  if (values.pointCheckTouched && points.length) {
    const recalled = points.filter(function (point) { return point.checked })
    payload.answer_point_count = points.length
    payload.recalled_point_count = recalled.length
    payload.recalled_point_indexes = recalled.map(function (point) { return point.index }).join(',')
  }
  return payload
}

module.exports = {
  FAST_RECALL_MS: FAST_RECALL_MS,
  decorateAnswerPoints: decorateAnswerPoints,
  setCheckedAnswerPoints: setCheckedAnswerPoints,
  countRecalledPoints: countRecalledPoints,
  recommendRating: recommendRating,
  buildAnswerPayload: buildAnswerPayload
}
