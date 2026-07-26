'use strict'

const SIGNAL_LABELS = {
  repeated_again: '近 30 天多次选择“重来”',
  slow_hard: '困难回忆耗时较长',
  tag_confusion: '同主题内容近期容易混淆',
  card_issue: '存在待核对的内容问题'
}

const ACTION_LABELS = {
  review_content: '对照来源核对卡片内容',
  split_card: '把过大的卡片拆成更小的问题',
  compare_cards: '并排比较容易混淆的相关卡片',
  reread_source: '先重读来源片段再进行回忆',
  written_recall: '进行一次不看提示的书写回忆'
}

function decorateRepairSuggestion(item) {
  const source = Object.assign({}, item.source || {})
  source.chapter_label = [source.chapter, source.section].filter(Boolean).join(' / ')
  const signals = (item.signals || []).map(function (signal, index) {
    return Object.assign({}, signal, {
      key: signal.code + '-' + index,
      label: SIGNAL_LABELS[signal.code] || '近期学习记录提示需要关注'
    })
  })
  const actions = (item.actions || []).map(function (action, index) {
    return Object.assign({}, action, {
      key: action.code + '-' + index,
      label: ACTION_LABELS[action.code] || action.reason || '复习相关内容'
    })
  })
  return Object.assign({}, item, {
    source: source,
    signals: signals,
    actions: actions,
    firstSignalLabel: signals.length ? signals[0].label : '近期学习记录提示需要关注',
    firstActionLabel: actions.length ? actions[0].label : '复习相关内容'
  })
}

module.exports = {
  decorateRepairSuggestion: decorateRepairSuggestion
}
