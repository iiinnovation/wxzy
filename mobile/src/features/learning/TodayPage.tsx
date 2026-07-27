import { AlertCircle, CalendarDays, LoaderCircle, Play } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AppRuntime } from '../../app/runtime'
import { withSession } from '../../app/session'
import type { DailyPlan } from '../../services/api'

const budgetPresets = [10, 20, 30]

export function TodayPage({ runtime }: { runtime: AppRuntime }) {
  const [plan, setPlan] = useState<DailyPlan | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [working, setWorking] = useState(false)

  const loadPlan = useCallback(async () => {
    try {
      setPlan(await withSession(runtime, (token) => runtime.api.getToday(token)))
      setStatus('ready')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '今日计划加载失败')
      setStatus('error')
    }
  }, [runtime])

  useEffect(() => {
    let cancelled = false
    void fetchToday(runtime)
      .then((value) => {
        if (cancelled) return
        setPlan(value)
        setStatus('ready')
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(reason instanceof Error ? reason.message : '今日计划加载失败')
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [runtime])

  const pending = useMemo(
    () => plan?.items.filter((item) => item.status === 'pending') ?? [],
    [plan]
  )

  async function adjustBudget(minutes: number) {
    if (!plan || working || minutes === plan.effective_budget_minutes) return
    setWorking(true)
    setError('')
    try {
      setPlan(await withSession(runtime, (token) => runtime.api.adjustTodayBudget(token, minutes)))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '学习时长调整失败')
    } finally {
      setWorking(false)
    }
  }

  async function startSession() {
    if (!plan || !pending.length || working) return
    setWorking(true)
    setError('')
    try {
      const session = await withSession(runtime, (token) => runtime.api.createStudySession(token, plan.id))
      window.location.hash = `/study/${session.id}`
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '学习会话创建失败')
      setWorking(false)
    }
  }

  if (status === 'loading') return <TodayLoading />
  if (status === 'error') {
    return (
      <main className="page page--centered">
        <section className="state-panel">
          <AlertCircle aria-hidden="true" size={24} />
          <h1>今日计划加载失败</h1>
          <p>{error}</p>
          <button className="secondary-button" onClick={() => { setStatus('loading'); setError(''); void loadPlan() }}>重新加载</button>
        </section>
      </main>
    )
  }

  if (!plan) return null
  return (
    <main className="page today-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">{plan.plan_date}</p>
          <h1>今日学习</h1>
        </div>
        <CalendarDays aria-hidden="true" size={25} />
      </header>

      <section className="today-summary" aria-label="今日计划摘要">
        <div><strong>{pending.length}</strong><span>待完成</span></div>
        <div><strong>{plan.estimated_minutes}</strong><span>预计分钟</span></div>
        <div><strong>{plan.due_count}</strong><span>到期复习</span></div>
      </section>

      <section className="today-section" aria-labelledby="budget-title">
        <div className="section-row">
          <h2 id="budget-title">学习时长</h2>
          <span>{plan.effective_budget_minutes} 分钟</span>
        </div>
        <div className="segmented-control" aria-label="调整学习时长">
          {budgetPresets.map((minutes) => (
            <button
              key={minutes}
              type="button"
              className={plan.effective_budget_minutes === minutes ? 'active' : ''}
              disabled={working}
              onClick={() => void adjustBudget(minutes)}
            >
              {minutes}
            </button>
          ))}
        </div>
      </section>

      <section className="today-section" aria-labelledby="tasks-title">
        <div className="section-row">
          <h2 id="tasks-title">计划任务</h2>
          <span>{pending.length ? `共 ${pending.length} 项` : '已完成'}</span>
        </div>
        {pending.length ? (
          <ol className="task-preview">
            {pending.slice(0, 5).map((item) => (
              <li key={item.id}>
                <span>{taskLabel(item.item_type)}</span>
                <small>{Math.max(1, Math.ceil(item.estimated_seconds / 60))} 分钟</small>
              </li>
            ))}
          </ol>
        ) : (
          <p className="empty-copy">今天的计划已完成，新的到期任务会自动进入后续计划。</p>
        )}
      </section>

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="primary-action" disabled={!pending.length || working} onClick={() => void startSession()}>
        {working ? <LoaderCircle className="spin" aria-hidden="true" size={20} /> : <Play aria-hidden="true" size={20} />}
        {pending.length ? '开始今日学习' : '今日已完成'}
      </button>
    </main>
  )
}

function TodayLoading() {
  return (
    <main className="page page--centered" aria-busy="true">
      <section className="state-panel">
        <p className="eyebrow">温习</p>
        <h1>正在生成今日计划</h1>
      </section>
    </main>
  )
}

async function fetchToday(runtime: AppRuntime) {
  return withSession(runtime, (token) => runtime.api.getToday(token))
}

function taskLabel(type: string) {
  return {
    due: '到期复习',
    overdue: '积压复习',
    new: '新卡学习',
    weak_topic: '薄弱点强化',
    repair: '错题修复',
    mixed_weekly: '周测回顾'
  }[type] ?? '学习任务'
}
