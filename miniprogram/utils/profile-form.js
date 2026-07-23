/**
 * Pure helpers for learning-profile form state.
 * Safe to require from Node tests and WeChat pages.
 */
'use strict'

var GOAL_OPTIONS = [
  { value: 'daily_learning', label: '日常巩固', hint: '每天保持少量复习' },
  { value: 'exam', label: '考试准备', hint: '按目标日期收紧计划' },
  { value: 'focused', label: '专项强化', hint: '优先高优先级学科' }
]

var MINUTE_PRESETS = [10, 20, 30]

var DAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

var DEFAULT_SUBJECTS = [
  '基础理论',
  '诊断学',
  '中药学',
  '方剂学',
  '内科学',
  '针灸学',
  '人文'
]

function cloneStudyDays(days) {
  var source = Array.isArray(days) && days.length === 7 ? days : [true, true, true, true, true, true, true]
  return source.map(function (item) {
    return Boolean(item)
  })
}

function defaultFormState() {
  return {
    goal_type: 'daily_learning',
    target_date: '',
    daily_minutes: 20,
    custom_minutes: '',
    study_days: [true, true, true, true, true, true, true],
    desired_retention: 0.9,
    new_card_ceiling: 5,
    display_name: '',
    timezone: 'Asia/Shanghai',
    subject_rows: DEFAULT_SUBJECTS.map(function (name) {
      return { name: name, priority: 3, assessment: 3, enabled: false }
    }),
    expected_updated_at: '',
    onboarding_completed: false
  }
}

function profileToForm(profile) {
  var form = defaultFormState()
  if (!profile || typeof profile !== 'object') {
    return form
  }

  form.goal_type = profile.goal_type || form.goal_type
  form.target_date = profile.target_date || ''
  form.daily_minutes = Number(profile.daily_minutes) || 20
  form.custom_minutes = MINUTE_PRESETS.indexOf(form.daily_minutes) >= 0 ? '' : String(form.daily_minutes)
  form.study_days = cloneStudyDays(profile.study_days)
  form.desired_retention =
    profile.desired_retention != null ? Number(profile.desired_retention) : 0.9
  form.new_card_ceiling =
    profile.new_card_ceiling != null ? Number(profile.new_card_ceiling) : 5
  form.display_name = profile.display_name || ''
  form.timezone = profile.timezone || 'Asia/Shanghai'
  form.expected_updated_at = profile.updated_at || ''
  form.onboarding_completed = Boolean(profile.onboarding_completed_at)

  var priorities = profile.subject_priorities || {}
  var assessments = profile.initial_self_assessment || {}
  var names = Object.keys(priorities)
  DEFAULT_SUBJECTS.forEach(function (name) {
    if (names.indexOf(name) < 0) names.push(name)
  })
  Object.keys(assessments).forEach(function (name) {
    if (names.indexOf(name) < 0) names.push(name)
  })

  form.subject_rows = names.map(function (name) {
    var hasPriority = Object.prototype.hasOwnProperty.call(priorities, name)
    var hasAssessment = Object.prototype.hasOwnProperty.call(assessments, name)
    return {
      name: name,
      priority: hasPriority ? Number(priorities[name]) : 3,
      assessment: hasAssessment ? Number(assessments[name]) : 3,
      enabled: hasPriority || hasAssessment
    }
  })

  return form
}

function subjectMapsFromRows(rows) {
  var priorities = {}
  var assessments = {}
  ;(rows || []).forEach(function (row) {
    if (!row || !row.enabled) return
    var name = String(row.name || '').trim()
    if (!name) return
    var priority = clampScore(row.priority)
    var assessment = clampScore(row.assessment)
    priorities[name] = priority
    assessments[name] = assessment
  })
  return { subject_priorities: priorities, initial_self_assessment: assessments }
}

function clampScore(value) {
  var n = Number(value)
  if (!Number.isFinite(n)) return 3
  if (n < 1) return 1
  if (n > 5) return 5
  return Math.round(n)
}

function resolveDailyMinutes(form) {
  var custom = String(form.custom_minutes || '').trim()
  if (custom) {
    var n = Number(custom)
    if (!Number.isFinite(n)) return null
    return Math.round(n)
  }
  var minutes = Number(form.daily_minutes)
  if (!Number.isFinite(minutes)) return null
  return Math.round(minutes)
}

function validateForm(form, options) {
  options = options || {}
  var errors = []
  var goal = form.goal_type
  if (goal !== 'daily_learning' && goal !== 'exam' && goal !== 'focused') {
    errors.push('请选择学习目的')
  }

  var minutes = resolveDailyMinutes(form)
  if (minutes == null || minutes < 5 || minutes > 240) {
    errors.push('每日分钟需在 5–240 之间')
  }

  var days = cloneStudyDays(form.study_days)
  if (!days.some(Boolean)) {
    errors.push('请至少选择一个学习日')
  }

  if (goal === 'exam' && options.requireExamDate) {
    if (!String(form.target_date || '').trim()) {
      errors.push('考试准备请填写目标日期')
    }
  }

  if (form.target_date) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(form.target_date))) {
      errors.push('目标日期格式应为 YYYY-MM-DD')
    }
  }

  var name = String(form.display_name || '').trim()
  if (name.length > 64) {
    errors.push('昵称不能超过 64 个字符')
  }

  return {
    ok: errors.length === 0,
    errors: errors,
    daily_minutes: minutes,
    study_days: days
  }
}

function buildUpdatePayload(form, options) {
  options = options || {}
  var validation = validateForm(form, options)
  if (!validation.ok) {
    var err = new Error(validation.errors[0] || '表单无效')
    err.code = 'FORM_INVALID'
    err.errors = validation.errors
    throw err
  }

  if (!form.expected_updated_at) {
    var missing = new Error('缺少档案版本，请刷新后重试')
    missing.code = 'PROFILE_VERSION_MISSING'
    throw missing
  }

  var maps = subjectMapsFromRows(form.subject_rows)
  var retention = Number(form.desired_retention)
  if (!Number.isFinite(retention)) retention = 0.9
  if (retention < 0.7) retention = 0.7
  if (retention > 0.99) retention = 0.99
  var ceiling = Number(form.new_card_ceiling)
  if (!Number.isFinite(ceiling)) ceiling = 5
  if (ceiling < 0) ceiling = 0
  if (ceiling > 100) ceiling = 100
  ceiling = Math.round(ceiling)
  var payload = {
    expected_updated_at: form.expected_updated_at,
    goal_type: form.goal_type,
    target_date: form.target_date ? String(form.target_date) : null,
    daily_minutes: validation.daily_minutes,
    study_days: validation.study_days,
    desired_retention: retention,
    new_card_ceiling: ceiling,
    subject_priorities: maps.subject_priorities,
    initial_self_assessment: maps.initial_self_assessment,
    display_name: String(form.display_name || '').trim() || null,
    timezone: form.timezone || 'Asia/Shanghai'
  }

  if (options.completeOnboarding) {
    payload.onboarding_completed = true
  } else if (options.onboarding_completed != null) {
    payload.onboarding_completed = Boolean(options.onboarding_completed)
  }

  return payload
}

function summarizeProfile(profile) {
  if (!profile) {
    return {
      goalLabel: '未设置',
      minutesLabel: '—',
      daysLabel: '—',
      onboardingDone: false,
      subjectsLabel: '未设置学科优先级'
    }
  }
  var goal = GOAL_OPTIONS.find(function (item) {
    return item.value === profile.goal_type
  })
  var days = cloneStudyDays(profile.study_days)
  var dayText = days
    .map(function (on, idx) {
      return on ? DAY_LABELS[idx] : null
    })
    .filter(Boolean)
    .join('、')
  var subjectCount = Object.keys(profile.subject_priorities || {}).length
  return {
    goalLabel: goal ? goal.label : profile.goal_type || '未设置',
    minutesLabel: (profile.daily_minutes || 0) + ' 分钟/天',
    daysLabel: dayText || '未选择',
    onboardingDone: Boolean(profile.onboarding_completed_at),
    subjectsLabel: subjectCount > 0 ? subjectCount + ' 个学科已设优先级' : '未设置学科优先级',
    targetDateLabel: profile.target_date || '',
    displayName: profile.display_name || ''
  }
}

function isOnboardingComplete(profile) {
  return Boolean(profile && profile.onboarding_completed_at)
}

module.exports = {
  GOAL_OPTIONS: GOAL_OPTIONS,
  MINUTE_PRESETS: MINUTE_PRESETS,
  DAY_LABELS: DAY_LABELS,
  DEFAULT_SUBJECTS: DEFAULT_SUBJECTS,
  defaultFormState: defaultFormState,
  profileToForm: profileToForm,
  subjectMapsFromRows: subjectMapsFromRows,
  resolveDailyMinutes: resolveDailyMinutes,
  validateForm: validateForm,
  buildUpdatePayload: buildUpdatePayload,
  summarizeProfile: summarizeProfile,
  isOnboardingComplete: isOnboardingComplete,
  cloneStudyDays: cloneStudyDays,
  clampScore: clampScore
}
