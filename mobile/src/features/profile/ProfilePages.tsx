/* eslint-disable react-hooks/set-state-in-effect */
import { Check, Download, LogOut, MonitorSmartphone, Pencil, ShieldCheck, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { AppRuntime } from '../../app/runtime'
import { withSession } from '../../app/session'
import { EmptyState, ErrorState, LoadingState, PageHeader, errorMessage } from '../../components/AsyncState'
import type { LearningProfile, LearningProfileUpdate, Owner, SessionDevice } from '../../services/api'

const dayLabels = ['一', '二', '三', '四', '五', '六', '日']
const subjects = ['基础理论', '诊断学', '中药学', '方剂学', '内科学', '针灸学', '人文']
const goalLabels = { daily_learning: '日常巩固', exam: '考试准备', focused: '专项强化' }
const sessionLabels = { active: '有效', expired: '已过期', revoked: '已撤销' }

export function MePage({ runtime, owner, onLogout }: { runtime: AppRuntime; owner: Owner; onLogout: () => Promise<void> }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [profile, setProfile] = useState<LearningProfile | null>(null)
  const [sessions, setSessions] = useState<SessionDevice[]>([])
  const [actionId, setActionId] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextProfile, nextSessions] = await withSession(runtime, (token) => Promise.all([
        runtime.api.getLearningProfile(token), runtime.api.listSessions(token)
      ]))
      setProfile(nextProfile)
      setSessions(nextSessions.items)
    } catch (reason) {
      setError(errorMessage(reason, '账户数据加载失败'))
    } finally {
      setLoading(false)
    }
  }, [runtime])
  useEffect(() => { void load() }, [load])

  async function revoke(sessionId: number) {
    if (actionId) return
    setActionId(sessionId)
    setError('')
    try {
      await withSession(runtime, (token) => runtime.api.revokeSession(token, sessionId))
      setSessions((rows) => rows.map((row) => row.id === sessionId ? { ...row, status: 'revoked', revoked_at: new Date().toISOString() } : row))
      setNotice('设备会话已撤销')
    } catch (reason) {
      setError(errorMessage(reason, '设备会话撤销失败'))
    } finally {
      setActionId(null)
    }
  }

  async function exportData() {
    if (exporting) return
    setExporting(true)
    setError('')
    try {
      const data = await withSession(runtime, (token) => runtime.api.exportOwnerData(token))
      const json = JSON.stringify(data, null, 2)
      const file = new File([json], `wenxi-data-${data.generated_at.slice(0, 10)}.json`, { type: 'application/json' })
      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], title: '温习学习数据' })
      } else {
        const url = URL.createObjectURL(file)
        const link = document.createElement('a')
        link.href = url
        link.download = file.name
        link.click()
        URL.revokeObjectURL(url)
      }
      setNotice('学习数据已导出')
    } catch (reason) {
      setError(errorMessage(reason, '学习数据导出失败'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <main className="page me-page">
      <PageHeader eyebrow="应用与数据" title="我的" />
      {loading ? <LoadingState label="正在同步账户数据" /> : null}
      {!loading && error && !profile ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!loading && profile ? (
        <>
          <section className="account-block">
            <div className="account-identity"><span>{(profile.display_name || owner.display_name || '温习用户').slice(0, 1)}</span><div><h2>{profile.display_name || owner.display_name || '温习用户'}</h2><p>{profile.timezone}</p></div></div>
            <a className="secondary-button" href="#/profile"><Pencil aria-hidden="true" size={17} />编辑档案</a>
          </section>
          <section className="profile-summary">
            <div><span>学习目的</span><strong>{goalLabels[profile.goal_type]}</strong></div>
            <div><span>每日时间</span><strong>{profile.daily_minutes} 分钟</strong></div>
            <div><span>学习日</span><strong>{profile.study_days.map((enabled, index) => enabled ? dayLabels[index] : '').filter(Boolean).join('、')}</strong></div>
            <div><span>优先学科</span><strong>{Object.keys(profile.subject_priorities).join('、') || '按内容顺序'}</strong></div>
          </section>
          <section className="settings-section">
            <div className="section-row"><h2>登录设备</h2><span>{sessions.filter((session) => session.status === 'active').length} 台有效</span></div>
            {sessions.length ? sessions.map((session) => (
              <div className="session-row" key={session.id}>
                <MonitorSmartphone aria-hidden="true" size={20} />
                <span><strong>{session.device_label || '未命名设备'}{session.current ? ' · 当前设备' : ''}</strong><small>登录 {dateTimeLabel(session.created_at)} · 到期 {dateTimeLabel(session.expires_at)}</small></span>
                {session.status === 'active' && !session.current ? <button className="icon-button danger" aria-label={`撤销 ${session.device_label || '设备'}`} disabled={actionId !== null} onClick={() => void revoke(session.id)}><Trash2 aria-hidden="true" size={18} /></button> : <em>{sessionLabels[session.status]}</em>}
              </div>
            )) : <EmptyState title="暂无设备会话" message="当前没有可管理的登录设备。" />}
          </section>
          <section className="settings-section">
            <h2>数据与隐私</h2>
            <p className="settings-copy"><ShieldCheck aria-hidden="true" size={19} />导出不包含 Token、激活码或服务端密钥。</p>
            <button className="secondary-button" disabled={exporting} onClick={() => void exportData()}><Download aria-hidden="true" size={17} />{exporting ? '正在导出' : '导出我的数据'}</button>
          </section>
          {notice ? <p className="success-message" role="status"><Check aria-hidden="true" size={17} />{notice}</p> : null}
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="secondary-button secondary-button--danger logout-button" onClick={() => void onLogout()}><LogOut aria-hidden="true" size={18} />退出这台设备</button>
        </>
      ) : null}
    </main>
  )
}

interface ProfileForm {
  displayName: string
  goalType: LearningProfile['goal_type']
  targetDate: string
  dailyMinutes: number
  studyDays: boolean[]
  desiredRetention: number
  newCardCeiling: number
  subjectRows: Array<{ name: string; enabled: boolean; priority: number; assessment: number }>
}

export function ProfileEditPage({ runtime }: { runtime: AppRuntime }) {
  const [profile, setProfile] = useState<LearningProfile | null>(null)
  const [form, setForm] = useState<ProfileForm | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const value = await withSession(runtime, (token) => runtime.api.getLearningProfile(token))
      setProfile(value)
      setForm(toForm(value))
    } catch (reason) {
      setError(errorMessage(reason, '学习档案加载失败'))
    } finally { setLoading(false) }
  }, [runtime])
  useEffect(() => { void load() }, [load])

  function patch(values: Partial<ProfileForm>) {
    setForm((current) => current ? { ...current, ...values } : current)
    setSaved(false)
    setError('')
  }

  function patchSubject(index: number, values: Partial<ProfileForm['subjectRows'][number]>) {
    if (!form) return
    patch({ subjectRows: form.subjectRows.map((row, rowIndex) => rowIndex === index ? { ...row, ...values } : row) })
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!form || !profile || saving) return
    if (!form.studyDays.some(Boolean)) { setError('请至少选择一个学习日'); return }
    if (form.dailyMinutes < 5 || form.dailyMinutes > 240) { setError('每日分钟需在 5 到 240 之间'); return }
    setSaving(true)
    setError('')
    const enabled = form.subjectRows.filter((row) => row.enabled)
    const payload: LearningProfileUpdate = {
      expected_updated_at: profile.updated_at,
      goal_type: form.goalType,
      target_date: form.targetDate || null,
      daily_minutes: Math.round(form.dailyMinutes),
      study_days: form.studyDays,
      desired_retention: form.desiredRetention,
      new_card_ceiling: Math.round(form.newCardCeiling),
      subject_priorities: Object.fromEntries(enabled.map((row) => [row.name, row.priority])),
      initial_self_assessment: Object.fromEntries(enabled.map((row) => [row.name, row.assessment])),
      onboarding_completed: true,
      display_name: form.displayName.trim() || null,
      timezone: profile.timezone
    }
    try {
      const updated = await withSession(runtime, (token) => runtime.api.updateLearningProfile(token, payload))
      setProfile(updated)
      setForm(toForm(updated))
      setSaved(true)
    } catch (reason) {
      setError(errorMessage(reason, '档案保存失败'))
    } finally { setSaving(false) }
  }

  return (
    <main className="page profile-page">
      <PageHeader eyebrow="学习偏好" title="档案设置" back="/me" />
      {loading ? <LoadingState label="正在加载档案" /> : null}
      {!loading && error && !form ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!loading && form ? (
        <form className="profile-form" onSubmit={(event) => void save(event)}>
          <section><h2>基本信息</h2><label>显示昵称<input value={form.displayName} maxLength={64} onChange={(event) => patch({ displayName: event.target.value })} /></label></section>
          <section><h2>学习目的</h2><div className="goal-control">{(Object.keys(goalLabels) as Array<LearningProfile['goal_type']>).map((goal) => <button type="button" className={form.goalType === goal ? 'active' : ''} key={goal} onClick={() => patch({ goalType: goal })}>{goalLabels[goal]}</button>)}</div>{form.goalType === 'exam' ? <label>目标日期<input type="date" value={form.targetDate} onChange={(event) => patch({ targetDate: event.target.value })} /></label> : null}</section>
          <section><h2>时间与学习日</h2><label>每日分钟<input type="number" min={5} max={240} value={form.dailyMinutes} onChange={(event) => patch({ dailyMinutes: Number(event.target.value) })} /></label><fieldset className="day-control"><legend>每周学习日</legend>{dayLabels.map((day, index) => <label key={day}><input type="checkbox" checked={form.studyDays[index]} onChange={() => patch({ studyDays: form.studyDays.map((value, i) => i === index ? !value : value) })} /><span>{day}</span></label>)}</fieldset></section>
          <section><h2>学科优先级</h2><div className="subject-settings">{form.subjectRows.map((row, index) => <div className={row.enabled ? 'subject-setting active' : 'subject-setting'} key={row.name}><label className="subject-toggle"><input type="checkbox" checked={row.enabled} onChange={(event) => patchSubject(index, { enabled: event.target.checked })} /><strong>{row.name}</strong></label>{row.enabled ? <><label>优先级 <output>{row.priority}</output><input type="range" min={1} max={5} value={row.priority} onChange={(event) => patchSubject(index, { priority: Number(event.target.value) })} /></label><label>当前基础 <output>{row.assessment}</output><input type="range" min={1} max={5} value={row.assessment} onChange={(event) => patchSubject(index, { assessment: Number(event.target.value) })} /></label></> : null}</div>)}</div></section>
          <section><h2>高级设置</h2><label>目标留存率 <output>{Math.round(form.desiredRetention * 100)}%</output><input type="range" min={0.7} max={0.99} step={0.01} value={form.desiredRetention} onChange={(event) => patch({ desiredRetention: Number(event.target.value) })} /></label><label>每日新卡上限<input type="number" min={0} max={100} value={form.newCardCeiling} onChange={(event) => patch({ newCardCeiling: Number(event.target.value) })} /></label></section>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          {saved ? <p className="success-message" role="status"><Check aria-hidden="true" size={17} />档案已保存</p> : null}
          <button className="primary-action" disabled={saving}>{saving ? '正在保存' : '保存档案'}</button>
        </form>
      ) : null}
    </main>
  )
}

function toForm(profile: LearningProfile): ProfileForm {
  return {
    displayName: profile.display_name ?? '', goalType: profile.goal_type, targetDate: profile.target_date ?? '',
    dailyMinutes: profile.daily_minutes, studyDays: [...profile.study_days], desiredRetention: profile.desired_retention,
    newCardCeiling: profile.new_card_ceiling,
    subjectRows: subjects.map((name) => ({ name, enabled: name in profile.subject_priorities || name in profile.initial_self_assessment, priority: profile.subject_priorities[name] ?? 3, assessment: profile.initial_self_assessment[name] ?? 3 }))
  }
}

function dateTimeLabel(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
