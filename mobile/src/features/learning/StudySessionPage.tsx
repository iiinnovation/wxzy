import { ArrowLeft, Check, LoaderCircle, PenLine, RotateCcw } from 'lucide-react'
import type { MouseEvent } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AppRuntime } from '../../app/runtime'
import { withSession } from '../../app/session'
import type { ReviewAttemptPayload, StudySessionNext, StudyTask } from '../../services/api'

const ratings = [
  { value: 1, label: '重来' },
  { value: 2, label: '困难' },
  { value: 3, label: '良好' },
  { value: 4, label: '轻松' }
]

export function StudySessionPage({ runtime, sessionId }: { runtime: AppRuntime; sessionId: number }) {
  const [result, setResult] = useState<StudySessionNext | null>(null)
  const [status, setStatus] = useState<'loading' | 'recall' | 'answer' | 'interrupted' | 'completed' | 'error'>('loading')
  const [error, setError] = useState('')
  const [writing, setWriting] = useState(false)
  const [writtenAnswer, setWrittenAnswer] = useState('')
  const [checkedPoints, setCheckedPoints] = useState<number[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [startedAt, setStartedAt] = useState(0)
  const [revealedAt, setRevealedAt] = useState<number | null>(null)
  const [pendingPayload, setPendingPayload] = useState<ReviewAttemptPayload | null>(null)

  const loadNext = useCallback(async () => {
    try {
      const next = await withSession(runtime, (token) => runtime.api.getNextTask(token, sessionId))
      setResult(next)
      if (next.session.status === 'interrupted') {
        setStatus('interrupted')
      } else if (!next.task) {
        const completed =
          next.session.status === 'completed'
            ? next.session
            : await withSession(runtime, (token) => runtime.api.completeStudySession(token, sessionId))
        setResult({ session: completed, task: null })
        setStatus('completed')
      } else {
        setStartedAt(performance.now())
        setRevealedAt(null)
        setPendingPayload(null)
        setWriting(false)
        setWrittenAnswer('')
        setCheckedPoints([])
        setStatus('recall')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '下一项学习任务加载失败')
      setStatus('error')
    }
  }, [runtime, sessionId])

  useEffect(() => {
    let cancelled = false
    void fetchNext(runtime, sessionId)
      .then((next) => {
        if (cancelled) return
        setResult(next)
        if (next.session.status === 'interrupted') {
          setStatus('interrupted')
        } else if (!next.task) {
          setStatus('completed')
        } else {
          setStartedAt(performance.now())
          setStatus('recall')
        }
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(reason instanceof Error ? reason.message : '下一项学习任务加载失败')
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [runtime, sessionId])

  const task = result?.task ?? null
  const progress = result?.session
  const answerPoints = task?.card.answer_points ?? []
  const sourceLabel = useMemo(() => {
    if (!task) return ''
    return [task.card.book_name, task.card.chapter].filter(Boolean).join(' · ')
  }, [task])

  function revealAnswer(event: MouseEvent<HTMLButtonElement>) {
    setRevealedAt(event.timeStamp)
    setStatus('answer')
  }

  async function submitRating(rating: number, eventTime: number) {
    if (!task || submitting) return
    setSubmitting(true)
    setError('')
    const payload = pendingPayload ?? buildAttemptPayload({
        sessionId,
        task,
        rating,
        responseMs: Math.max(0, Math.round(eventTime - startedAt)),
        recallMs: Math.max(0, Math.round((revealedAt ?? eventTime) - startedAt)),
        writing,
        writtenAnswer,
        checkedPoints
      })
    if (!pendingPayload) setPendingPayload(payload)
    try {
      await withSession(runtime, (token) => runtime.api.submitReviewAttempt(token, payload))
      setPendingPayload(null)
      setSubmitting(false)
      setStatus('loading')
      await loadNext()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '评分保存失败，请原样重试')
      setSubmitting(false)
    }
  }

  async function resume() {
    setStatus('loading')
    setError('')
    try {
      await withSession(runtime, (token) => runtime.api.resumeStudySession(token, sessionId))
      await loadNext()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '恢复学习失败')
      setStatus('error')
    }
  }

  const exitSession = useCallback(async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      if (result?.session.status === 'active') {
        await withSession(runtime, (token) => runtime.api.interruptStudySession(token, sessionId))
      }
      window.location.hash = '/today'
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '学习进度保存失败')
      setSubmitting(false)
    }
  }, [result, runtime, sessionId, submitting])

  useEffect(() => {
    const onNativeBack = () => { void exitSession() }
    window.addEventListener('wenxi:study-back', onNativeBack)
    return () => window.removeEventListener('wenxi:study-back', onNativeBack)
  }, [exitSession])

  if (status === 'loading') return <SessionLoading />
  if (status === 'error') {
    return <SessionState title="学习任务加载失败" message={error} action="重新加载" onAction={loadNext} />
  }
  if (status === 'interrupted') {
    return <SessionState title="学习已暂停" message="进度已保留，可以从当前任务继续。" action="继续学习" onAction={resume} />
  }
  if (status === 'completed') {
    return <SessionState title="今日学习完成" message={`已完成 ${progress?.completed_task_count ?? 0} 项任务。`} action="返回今日" onAction={async () => { window.location.hash = '/today' }} />
  }
  if (!task || !progress) return null

  return (
    <main className="study-page">
      <header className="study-toolbar">
        <button type="button" aria-label="保存并退出" onClick={() => void exitSession()} disabled={submitting}>
          <ArrowLeft aria-hidden="true" size={22} />
        </button>
        <div>
          <span>{progress.completed_task_count + 1} / {progress.planned_task_count}</span>
          <progress value={progress.completed_task_count} max={Math.max(progress.planned_task_count, 1)} />
        </div>
      </header>

      <article className="study-card">
        <p className="eyebrow">{sourceLabel || '今日任务'}</p>
        <h1>{task.card.question}</h1>

        {status === 'recall' ? (
          <section className="recall-area">
            <p>先在心中回忆，再查看答案。</p>
            <button className="text-action" type="button" onClick={() => setWriting((value) => !value)}>
              <PenLine aria-hidden="true" size={18} />
              {writing ? '收起书写' : '书写强化'}
            </button>
            {writing ? (
              <textarea
                aria-label="写下回忆内容"
                value={writtenAnswer}
                maxLength={4000}
                onChange={(event) => setWrittenAnswer(event.target.value)}
                placeholder="写下你记得的关键词或完整答案"
              />
            ) : null}
            <button className="primary-action" type="button" onClick={revealAnswer}>查看答案</button>
          </section>
        ) : (
          <section className="answer-area">
            <h2>参考答案</h2>
            <p className="answer-text">{task.card.answer}</p>
            {answerPoints.length ? (
              <fieldset className="answer-points">
                <legend>我回忆到了</legend>
                {answerPoints.map((point, index) => (
                  <label key={`${index}-${point}`}>
                    <input
                      type="checkbox"
                      checked={checkedPoints.includes(index)}
                      disabled={submitting || pendingPayload !== null}
                      onChange={() => setCheckedPoints((values) => values.includes(index) ? values.filter((value) => value !== index) : [...values, index])}
                    />
                    <span>{point}</span>
                  </label>
                ))}
              </fieldset>
            ) : null}
            {task.card.source_excerpt ? (
              <details className="source-excerpt">
                <summary>查看来源摘录</summary>
                <p>{task.card.source_excerpt}</p>
              </details>
            ) : null}
          </section>
        )}
      </article>

      {status === 'answer' ? (
        <footer className="rating-footer">
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <div className="rating-grid">
            {ratings.map((rating) => (
              <button key={rating.value} type="button" disabled={submitting || (pendingPayload !== null && pendingPayload.rating !== rating.value)} onClick={(event) => void submitRating(rating.value, event.timeStamp)}>
                {submitting && pendingPayload?.rating === rating.value ? <LoaderCircle className="spin" aria-hidden="true" size={18} /> : null}
                <strong>{rating.value}</strong><span>{rating.label}</span>
              </button>
            ))}
          </div>
          {pendingPayload && error ? (
            <button className="retry-submit" type="button" onClick={(event) => void submitRating(pendingPayload.rating, event.timeStamp)}>
              <RotateCcw aria-hidden="true" size={17} />原样重试
            </button>
          ) : null}
        </footer>
      ) : null}
    </main>
  )
}

function SessionLoading() {
  return <main className="study-page study-page--centered" aria-busy="true"><LoaderCircle className="spin" aria-hidden="true" size={28} /><p>正在加载下一项</p></main>
}

function SessionState({ title, message, action, onAction }: { title: string; message: string; action: string; onAction: () => Promise<void> }) {
  return (
    <main className="study-page study-page--centered">
      <Check aria-hidden="true" size={31} />
      <h1>{title}</h1><p>{message}</p>
      <button className="primary-action" type="button" onClick={() => void onAction()}>{action}</button>
    </main>
  )
}

async function fetchNext(runtime: AppRuntime, sessionId: number): Promise<StudySessionNext> {
  const next = await withSession(runtime, (token) => runtime.api.getNextTask(token, sessionId))
  if (next.session.status !== 'interrupted' && !next.task && next.session.status !== 'completed') {
    return {
      session: await withSession(runtime, (token) => runtime.api.completeStudySession(token, sessionId)),
      task: null
    }
  }
  return next
}

function buildAttemptPayload(input: {
  sessionId: number
  task: StudyTask
  rating: number
  responseMs: number
  recallMs: number
  writing: boolean
  writtenAnswer: string
  checkedPoints: number[]
}): ReviewAttemptPayload {
  return {
    session_id: input.sessionId,
    card_id: input.task.card.id,
    card_revision: input.task.card_revision,
    client_attempt_id: createAttemptId(input.sessionId, input.task.card.id),
    rating: input.rating,
    response_ms: input.responseMs,
    hint_used: false,
    reveal_count: 1,
    answer_payload: {
      recall_mode: input.writing ? 'writing' : 'quick',
      recall_ms: input.recallMs,
      written_answer: input.writtenAnswer.trim(),
      points_total: input.task.card.answer_points.length,
      points_recalled: input.checkedPoints.length,
      point_indices: [...input.checkedPoints].sort((a, b) => a - b).join(',')
    },
    expected_due_at: input.task.review_state.due_at,
    expected_state: input.task.review_state.state,
    expected_reps: input.task.review_state.reps
  }
}

function createAttemptId(sessionId: number, cardId: number) {
  const random = crypto.getRandomValues(new Uint32Array(1))[0].toString(36)
  return `android-${sessionId}-${cardId}-${Date.now().toString(36)}-${random}`
}
