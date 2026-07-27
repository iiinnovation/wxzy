/* eslint-disable react-hooks/set-state-in-effect */
import { BookOpen, CheckCircle2, ChevronRight, Pause, Play, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import type { AppRuntime } from '../../app/runtime'
import { withSession } from '../../app/session'
import { EmptyState, ErrorState, LoadingState, PageHeader, errorMessage } from '../../components/AsyncState'
import type { CatalogBook, CatalogCard, CatalogCardDetail, CatalogChapter } from '../../services/api'

type ViewState = 'loading' | 'ready' | 'empty' | 'error'

export function SubjectsPage({ runtime }: { runtime: AppRuntime }) {
  const [state, setState] = useState<ViewState>('loading')
  const [books, setBooks] = useState<CatalogBook[]>([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setState('loading')
    try {
      const rows = await withSession(runtime, (token) => runtime.api.listBooks(token))
      setBooks(rows)
      setState(rows.length ? 'ready' : 'empty')
    } catch (reason) {
      setError(errorMessage(reason, '学科目录加载失败'))
      setState('error')
    }
  }, [runtime])

  useEffect(() => { void load() }, [load])

  return (
    <main className="page catalog-page">
      <PageHeader eyebrow="七本学习资料" title="学科" />
      {state === 'loading' ? <LoadingState label="正在加载学习目录" /> : null}
      {state === 'error' ? <ErrorState message={error} retry={() => void load()} /> : null}
      {state === 'empty' ? <EmptyState title="尚无已发布内容" message="内容通过审核并发布后会出现在这里。" /> : null}
      {state === 'ready' ? (
        <div className="book-list">
          {books.map((book) => {
            const progress = book.active_card_count
              ? Math.round((book.mastered_card_count / book.active_card_count) * 100)
              : 0
            return (
              <a className="book-row" href={`#/book/${book.id}?name=${encodeURIComponent(book.name)}`} key={book.id}>
                <span className="book-row__icon"><BookOpen aria-hidden="true" size={20} /></span>
                <span className="book-row__body">
                  <strong>{book.name}</strong>
                  <span>{book.chapter_count} 章 · {book.published_card_count} 张已发布</span>
                  <span>已加入 {book.enrolled_card_count} · 学习中 {book.active_card_count} · 掌握 {book.mastered_card_count}</span>
                  <span className="compact-progress"><i style={{ width: `${progress}%` }} /></span>
                </span>
                <ChevronRight aria-hidden="true" size={20} />
              </a>
            )
          })}
        </div>
      ) : null}
    </main>
  )
}

function chapterAction(chapter: CatalogChapter) {
  if (chapter.published_card_count > chapter.enrolled_card_count) return { type: 'join' as const, label: '加入本章其余卡片' }
  if (chapter.active_card_count > 0) return { type: 'suspend' as const, label: '暂停本章' }
  if (chapter.suspended_card_count > 0) return { type: 'resume' as const, label: '恢复本章' }
  return { type: 'none' as const, label: chapter.enrolled_card_count ? '等待计划引入' : '暂无可加入卡片' }
}

export function ChapterPage({ runtime, bookId, bookName }: { runtime: AppRuntime; bookId: number; bookName: string }) {
  const [state, setState] = useState<ViewState>('loading')
  const [chapters, setChapters] = useState<CatalogChapter[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [cards, setCards] = useState<CatalogCard[]>([])
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [cardsLoading, setCardsLoading] = useState(false)
  const [changing, setChanging] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const selected = useMemo(() => chapters.find((chapter) => chapter.id === selectedId) ?? null, [chapters, selectedId])

  const loadCards = useCallback(async (chapterId: number, append = false, search = query) => {
    setCardsLoading(true)
    setError('')
    try {
      const nextOffset = append ? offset : 0
      const page = await withSession(runtime, (token) => runtime.api.searchCards(token, {
        bookId,
        chapterId,
        query: search,
        offset: nextOffset,
        limit: 20
      }))
      setCards((current) => append ? [...current, ...page.items] : page.items)
      setOffset(nextOffset + page.items.length)
      setHasMore(page.has_more)
    } catch (reason) {
      setError(errorMessage(reason, '卡片列表加载失败'))
    } finally {
      setCardsLoading(false)
    }
  }, [bookId, offset, query, runtime])

  const loadChapters = useCallback(async () => {
    setState('loading')
    setError('')
    try {
      const rows = await withSession(runtime, (token) => runtime.api.listChapters(token, bookId))
      setChapters(rows)
      const nextId = rows.some((row) => row.id === selectedId) ? selectedId : rows[0]?.id ?? null
      setSelectedId(nextId)
      setState(rows.length ? 'ready' : 'empty')
      if (nextId) await loadCards(nextId, false)
    } catch (reason) {
      setError(errorMessage(reason, '章节目录加载失败'))
      setState('error')
    }
  }, [bookId, loadCards, runtime, selectedId])

  useEffect(() => { void loadChapters() }, [bookId, runtime]) // eslint-disable-line react-hooks/exhaustive-deps

  async function selectChapter(chapterId: number) {
    setSelectedId(chapterId)
    setCards([])
    setOffset(0)
    setQuery('')
    setNotice('')
    await loadCards(chapterId, false, '')
  }

  async function changeChapter() {
    if (!selected || changing) return
    const action = chapterAction(selected)
    if (action.type === 'none') return
    setChanging(true)
    setError('')
    try {
      if (action.type === 'join') {
        const result = await withSession(runtime, (token) => runtime.api.enroll(token, {
          scope: 'chapter', chapter_id: selected.id, priority: 60
        }))
        setNotice(result.created_count ? `已加入 ${result.created_count} 张卡片` : '本章卡片已经加入')
      } else {
        const status = action.type === 'suspend' ? 'suspended' : 'active'
        const result = await withSession(runtime, (token) => runtime.api.updateChapterEnrollments(token, selected.id, status))
        setNotice(`${action.type === 'suspend' ? '已暂停' : '已恢复'} ${result.updated_count} 张卡片`)
      }
      const rows = await withSession(runtime, (token) => runtime.api.listChapters(token, bookId))
      setChapters(rows)
    } catch (reason) {
      setError(errorMessage(reason, '章节状态更新失败'))
    } finally {
      setChanging(false)
    }
  }

  const action = selected ? chapterAction(selected) : null

  return (
    <main className="page chapter-page">
      <PageHeader eyebrow="学习目录" title={bookName || '章节'} back="/subjects" />
      {state === 'loading' ? <LoadingState label="正在加载章节" /> : null}
      {state === 'error' ? <ErrorState message={error} retry={() => void loadChapters()} /> : null}
      {state === 'empty' ? <EmptyState title="暂无可学习章节" message="该书尚未发布章节卡片。" /> : null}
      {state === 'ready' ? (
        <>
          <div className="chapter-tabs" role="tablist" aria-label="章节">
            {chapters.map((chapter) => (
              <button key={chapter.id} role="tab" aria-selected={chapter.id === selectedId} className={chapter.id === selectedId ? 'active' : ''} onClick={() => void selectChapter(chapter.id)}>
                {chapter.title}
              </button>
            ))}
          </div>
          {selected ? (
            <section className="chapter-summary">
              <div>
                <h2>{selected.title}</h2>
                <p>PDF {selected.pdf_page_start}-{selected.pdf_page_end} 页 · 发布 {selected.published_card_count} · 已加入 {selected.enrolled_card_count}</p>
                <p>排队 {selected.queued_card_count} · 学习中 {selected.active_card_count} · 暂停 {selected.suspended_card_count}</p>
              </div>
              <button className="secondary-button" disabled={changing || action?.type === 'none'} onClick={() => void changeChapter()}>
                {action?.type === 'suspend' ? <Pause aria-hidden="true" size={17} /> : <Play aria-hidden="true" size={17} />}
                {changing ? '正在更新' : action?.label}
              </button>
              {notice ? <p className="success-message" role="status"><CheckCircle2 aria-hidden="true" size={17} />{notice}</p> : null}
            </section>
          ) : null}
          <form className="catalog-search" onSubmit={(event) => { event.preventDefault(); if (selected) void loadCards(selected.id, false) }}>
            <label htmlFor="card-query">搜索本章卡片</label>
            <div><input id="card-query" value={query} onChange={(event) => setQuery(event.target.value)} /><button aria-label="搜索" disabled={cardsLoading}><Search aria-hidden="true" size={19} /></button></div>
          </form>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <div className="card-list">
            {cards.map((card) => (
              <a className="card-row" href={`#/card/${card.id}`} key={card.id}>
                <span><strong>{card.question}</strong><small>{[card.chapter, card.source_pages.length ? `PDF ${card.source_pages[0]}` : '来源可查看'].filter(Boolean).join(' · ')}</small></span>
                <ChevronRight aria-hidden="true" size={19} />
              </a>
            ))}
          </div>
          {!cardsLoading && !cards.length ? <EmptyState title="没有匹配卡片" message="可以更换关键词或选择其他章节。" /> : null}
          {cardsLoading ? <LoadingState label="正在加载卡片" /> : null}
          {hasMore && selected ? <button className="load-more" disabled={cardsLoading} onClick={() => void loadCards(selected.id, true)}>加载更多</button> : null}
        </>
      ) : null}
    </main>
  )
}

export function CardDetailPage({ runtime, cardId }: { runtime: AppRuntime; cardId: number }) {
  const [state, setState] = useState<ViewState>('loading')
  const [detail, setDetail] = useState<CatalogCardDetail | null>(null)
  const [error, setError] = useState('')
  const [changing, setChanging] = useState(false)

  const load = useCallback(async () => {
    setState('loading')
    try {
      const result = await withSession(runtime, (token) => runtime.api.getCard(token, cardId))
      setDetail(result)
      setState('ready')
    } catch (reason) {
      setError(errorMessage(reason, '卡片详情加载失败'))
      setState('error')
    }
  }, [cardId, runtime])

  useEffect(() => { void load() }, [load])

  async function changeEnrollment() {
    if (!detail || changing) return
    setChanging(true)
    setError('')
    try {
      if (!detail.enrollment_id) {
        await withSession(runtime, (token) => runtime.api.enroll(token, { scope: 'card', card_id: cardId, priority: 60 }))
      } else {
        const status = detail.enrollment_status === 'suspended' ? 'active' : 'suspended'
        await withSession(runtime, (token) => runtime.api.updateEnrollment(token, detail.enrollment_id!, status))
      }
      await load()
    } catch (reason) {
      setError(errorMessage(reason, '卡片学习状态更新失败'))
    } finally {
      setChanging(false)
    }
  }

  return (
    <main className="page card-detail-page">
      <PageHeader eyebrow="已发布学习卡" title="卡片详情" back="/subjects" />
      {state === 'loading' ? <LoadingState label="正在读取卡片" /> : null}
      {state === 'error' ? <ErrorState message={error} retry={() => void load()} /> : null}
      {state === 'ready' && detail ? (
        <article>
          <p className="eyebrow">{[detail.card.book_name, detail.card.chapter, detail.card.section].filter(Boolean).join(' · ')}</p>
          <h1>{detail.card.question}</h1>
          <section className="detail-section"><h2>参考答案</h2><p className="long-copy">{detail.card.answer}</p></section>
          {detail.card.answer_points.length ? <section className="detail-section"><h2>审核要点</h2><ul>{detail.card.answer_points.map((point) => <li key={point}>{point}</li>)}</ul></section> : null}
          <section className="detail-section">
            <div className="section-row"><h2>学习状态</h2><span>{detail.mastered ? '已掌握' : detail.enrollment_status ?? '未加入'}</span></div>
            <button className="secondary-button" disabled={changing || detail.enrollment_status === 'retired'} onClick={() => void changeEnrollment()}>
              {changing ? '正在更新' : !detail.enrollment_id ? '加入学习' : detail.enrollment_status === 'suspended' ? '恢复学习' : '暂停学习'}
            </button>
            {error ? <p className="form-error" role="alert">{error}</p> : null}
          </section>
          <section className="detail-section source-list"><h2>来源</h2>
            {detail.sources.map((source) => <details key={source.id} open={detail.sources.length === 1}>
              <summary>{source.document_title} · PDF {source.pdf_page_number_start}{source.pdf_page_number_end !== source.pdf_page_number_start ? `-${source.pdf_page_number_end}` : ''}</summary>
              <p className="source-path">{source.chapter_path.join(' / ')}</p>
              <p className="long-copy">{source.excerpt}</p>
            </details>)}
          </section>
        </article>
      ) : null}
    </main>
  )
}
