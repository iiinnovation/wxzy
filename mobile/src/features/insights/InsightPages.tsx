/* eslint-disable react-hooks/set-state-in-effect */
import { AlertTriangle, ArrowRight, CalendarDays, FileText, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AppRuntime } from '../../app/runtime'
import { withSession } from '../../app/session'
import { EmptyState, ErrorState, LoadingState, PageHeader, errorMessage } from '../../components/AsyncState'
import type { DailyPlan, InsightSummary, InsightWorkload, RepairSuggestion } from '../../services/api'

const trendLabels = {
  insufficient: '数据还不够',
  improving: '正在改善',
  stable: '保持稳定',
  declining: '需要关注'
}

const signalLabels: Record<string, string> = {
  repeated_again: '近期多次选择重来',
  slow_hard: '困难回忆耗时较长',
  tag_confusion: '同主题内容容易混淆',
  card_issue: '存在待核对的内容问题'
}

const actionLabels: Record<string, string> = {
  review_content: '对照来源核对卡片内容',
  split_card: '把过大的卡片拆小',
  compare_cards: '比较容易混淆的卡片',
  reread_source: '先重读来源再回忆',
  written_recall: '进行一次书写回忆'
}

export function InsightsPage({ runtime }: { runtime: AppRuntime }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState<InsightSummary | null>(null)
  const [workload, setWorkload] = useState<InsightWorkload | null>(null)
  const [weak, setWeak] = useState<RepairSuggestion[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [nextSummary, nextWorkload, nextWeak] = await withSession(runtime, (token) => Promise.all([
        runtime.api.getInsightSummary(token),
        runtime.api.getInsightWorkload(token),
        runtime.api.getWeakTopics(token, 0, 5)
      ]))
      setSummary(nextSummary)
      setWorkload(nextWorkload)
      setWeak(nextWeak.items)
    } catch (reason) {
      setError(errorMessage(reason, '进度数据加载失败'))
    } finally {
      setLoading(false)
    }
  }, [runtime])

  useEffect(() => { void load() }, [load])
  const maximumMinutes = useMemo(() => Math.max(1, ...(workload?.days ?? []).flatMap((day) => [day.estimated_minutes, day.budget_minutes])), [workload])

  return (
    <main className="page insights-page">
      <PageHeader eyebrow="学习事实与未来负荷" title="进度" />
      {loading ? <LoadingState label="正在汇总学习记录" /> : null}
      {!loading && error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!loading && summary && workload ? (
        <>
          <section className="metric-strip">
            <div><strong>{summary.today_actual_minutes}</strong><span>今日分钟</span></div>
            <div><strong>{summary.today_review_count}</strong><span>今日复习</span></div>
            <div><strong>{summary.backlog_count}</strong><span>当前积压</span></div>
            <div><strong>{summary.study_days}</strong><span>学习天数</span></div>
          </section>
          <section className="insight-block">
            <h2>内容与掌握</h2>
            <dl className="fact-list">
              <div><dt>内容覆盖</dt><dd>{summary.content.covered_page_count} / {summary.content.document_page_count} 页</dd></div>
              <div><dt>已发布卡片</dt><dd>{summary.content.published_card_count}</dd></div>
              <div><dt>已加入学习</dt><dd>{summary.content.enrolled_card_count}</dd></div>
              <div><dt>当前掌握</dt><dd>{summary.content.mastered_card_count}</dd></div>
            </dl>
          </section>
          <section className="insight-block">
            <div className="section-row"><h2>未来 7 天</h2><span>{workload.overloaded ? '存在超载' : '预算内'}</span></div>
            <div className="workload-list">
              {workload.days.map((day) => (
                <div className="workload-row" key={day.local_date}>
                  <span>{dateLabel(day.local_date)}</span>
                  <span className="workload-track"><i className={day.overloaded ? 'overloaded' : ''} style={{ width: `${Math.round((day.estimated_minutes / maximumMinutes) * 100)}%` }} /></span>
                  <strong>{day.estimated_minutes} 分钟</strong>
                </div>
              ))}
            </div>
          </section>
          <section className="insight-block">
            <h2>学科趋势</h2>
            {summary.subjects.length ? summary.subjects.map((subject) => (
              <div className="trend-row" key={subject.subject}>
                <span><strong>{subject.subject}</strong><small>30 天 {subject.attempt_count_30d} 次 · 重来 {subject.again_count_30d} · 困难 {subject.hard_count_30d}</small></span>
                <span>{trendLabels[subject.trend]}</span>
              </div>
            )) : <EmptyState title="数据还不够" message="完成几次学习后会显示学科趋势。" />}
          </section>
          <section className="insight-block">
            <div className="section-row"><h2>薄弱点</h2><a href="#/weak">查看全部</a></div>
            {weak.length ? weak.map((item) => (
              <a className="weak-row" href={`#/weak/${item.card_id}`} key={item.card_id}>
                <AlertTriangle aria-hidden="true" size={19} />
                <span><strong>{item.topic}</strong><small>{signalLabels[item.signals[0]?.code] ?? item.reason_detail}</small></span>
                <ArrowRight aria-hidden="true" size={18} />
              </a>
            )) : <EmptyState title="暂未发现明确薄弱点" message="建议只会由真实学习记录触发。" />}
          </section>
          <a className="command-link" href="#/weekly"><CalendarDays aria-hidden="true" size={20} /><span><strong>本周混合测试</strong><small>跨章节检查脱离原文后的回忆</small></span><ArrowRight aria-hidden="true" size={19} /></a>
        </>
      ) : null}
    </main>
  )
}

export function WeakTopicsPage({ runtime, targetCardId }: { runtime: AppRuntime; targetCardId?: number }) {
  const [items, setItems] = useState<RepairSuggestion[]>([])
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (append = false) => {
    setLoading(true)
    setError('')
    try {
      let nextOffset = append ? offset : 0
      let collected: RepairSuggestion[] = append ? items : []
      let more = false
      do {
        const page = await withSession(runtime, (token) => runtime.api.getWeakTopics(token, nextOffset, 20))
        collected = [...collected, ...page.items]
        nextOffset += page.items.length
        more = page.has_more
      } while (targetCardId && !collected.some((item) => item.card_id === targetCardId) && more)
      setItems(targetCardId ? collected.filter((item) => item.card_id === targetCardId) : collected)
      setOffset(nextOffset)
      setHasMore(more && !targetCardId)
    } catch (reason) {
      setError(errorMessage(reason, '薄弱点加载失败'))
    } finally {
      setLoading(false)
    }
  }, [items, offset, runtime, targetCardId])

  useEffect(() => { void load(false) }, [runtime, targetCardId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <main className="page weak-page">
      <PageHeader eyebrow="基于真实学习记录" title="薄弱点" back="/insights" />
      {loading && !items.length ? <LoadingState label="正在分析薄弱记录" /> : null}
      {error ? <ErrorState message={error} retry={() => void load(false)} /> : null}
      {!loading && !error && !items.length ? <EmptyState title="暂未发现薄弱点" message="继续完成学习后，系统会给出有证据的修复建议。" /> : null}
      <div className="weak-list">
        {items.map((item) => (
          <article className="weak-detail" key={item.card_id}>
            <div className="weak-detail__heading"><AlertTriangle aria-hidden="true" size={20} /><div><h2>{item.topic}</h2><p>严重度 {item.severity_score}</p></div></div>
            <div className="evidence-grid"><span>尝试 {item.evidence.attempt_count}</span><span>重来 {item.evidence.again_count}</span><span>困难 {item.evidence.hard_count}</span></div>
            <section><h3>为什么需要关注</h3><ul>{item.signals.map((signal, index) => <li key={`${signal.code}-${index}`}>{signalLabels[signal.code] ?? signal.detail}</li>)}</ul></section>
            <section><h3>建议动作</h3><ul>{item.actions.map((action, index) => <li key={`${action.code}-${index}`}>{actionLabels[action.code] ?? action.reason}</li>)}</ul></section>
            <details className="source-detail"><summary><FileText aria-hidden="true" size={17} />查看来源</summary><p>{item.source.book_name} · {[item.source.chapter, item.source.section].filter(Boolean).join(' / ')}</p><p className="long-copy">{item.source.excerpt}</p></details>
            <a className="text-link" href={`#/card/${item.card_id}`}>打开卡片详情 <ArrowRight aria-hidden="true" size={16} /></a>
          </article>
        ))}
      </div>
      {hasMore ? <button className="load-more" disabled={loading} onClick={() => void load(true)}>{loading ? '正在加载' : '加载更多'}</button> : null}
    </main>
  )
}

export function WeeklyTestPage({ runtime }: { runtime: AppRuntime }) {
  const [plan, setPlan] = useState<DailyPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try { setPlan(await withSession(runtime, (token) => runtime.api.getToday(token))) }
    catch (reason) { setError(errorMessage(reason, '周测计划加载失败')) }
    finally { setLoading(false) }
  }, [runtime])
  useEffect(() => { void load() }, [load])

  const mixedPending = plan?.items.filter((item) => item.item_type === 'mixed_weekly' && item.status === 'pending').length ?? 0
  const mixedCompleted = plan?.items.filter((item) => item.item_type === 'mixed_weekly' && item.status === 'completed').length ?? 0
  const pendingBefore = plan?.items.filter((item) => item.status === 'pending' && item.item_type !== 'mixed_weekly').length ?? 0

  async function start() {
    if (!plan || starting) return
    setStarting(true)
    setError('')
    try {
      const session = await withSession(runtime, (token) => runtime.api.createStudySession(token, plan.id))
      window.location.hash = `/study/${session.id}`
    } catch (reason) {
      setError(errorMessage(reason, '周测启动失败'))
      setStarting(false)
    }
  }

  return (
    <main className="page weekly-page">
      <PageHeader eyebrow="跨章节回忆" title="本周混合测试" back="/insights" />
      {loading ? <LoadingState label="正在读取本周计划" /> : null}
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {!loading && !error ? (
        <section className="weekly-content">
          <TrendingUp aria-hidden="true" size={32} />
          <p>混合测试用于验证脱离原文后的掌握，不会用一次结果重排全部学习状态。</p>
          <dl className="fact-list"><div><dt>待完成混合题</dt><dd>{mixedPending}</dd></div><div><dt>今日已完成</dt><dd>{mixedCompleted}</dd></div><div><dt>排在周测前的任务</dt><dd>{pendingBefore}</dd></div></dl>
          {mixedPending ? <button className="primary-action" disabled={starting} onClick={() => void start()}>{starting ? '正在开始' : `开始 ${mixedPending} 项混合练习`}</button> : <EmptyState title={mixedCompleted ? '本周测试已完成' : '本周暂无混合测试'} message={mixedCompleted ? '结果已经计入学习记录。' : '系统会在具备足够已学习内容时安排。'} />}
        </section>
      ) : null}
    </main>
  )
}

function dateLabel(value: string) {
  const date = new Date(`${value}T00:00:00`)
  return `${date.getMonth() + 1}/${date.getDate()}`
}
