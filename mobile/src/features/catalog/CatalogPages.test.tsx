import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AppRuntime } from '../../app/runtime'
import { createMemorySessionStore } from '../../platform/sessionStore'
import type { CatalogChapter } from '../../services/api'
import { createMobileApiStub } from '../../test/mobileApiStub'
import { ChapterPage, SubjectsPage } from './CatalogPages'

function runtime(api = createMobileApiStub()): AppRuntime {
  return { api, sessionStore: createMemorySessionStore({ accessToken: 'token', expiresAt: '2099-01-01T00:00:00Z' }) }
}

test('shows published books and their learning progress', async () => {
  const api = createMobileApiStub({ listBooks: vi.fn().mockResolvedValue([{ id: 3, name: '中医基础理论', subject: '基础理论', chapter_count: 4, published_card_count: 18, enrolled_card_count: 6, queued_card_count: 2, active_card_count: 4, suspended_card_count: 0, mastered_card_count: 2 }]) })
  render(<SubjectsPage runtime={runtime(api)} />)

  expect(await screen.findByText('中医基础理论')).toBeInTheDocument()
  expect(screen.getByText('4 章 · 18 张已发布')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /中医基础理论/ })).toHaveAttribute('href', '#/book/3?name=%E4%B8%AD%E5%8C%BB%E5%9F%BA%E7%A1%80%E7%90%86%E8%AE%BA')
})

test('joins the remaining cards in a chapter with a submission lock', async () => {
  const chapter: CatalogChapter = { id: 8, parent_id: null, title: '阴阳学说', level: 0, sort_order: 1, pdf_page_start: 10, pdf_page_end: 30, published_card_count: 5, enrolled_card_count: 2, queued_card_count: 1, active_card_count: 1, suspended_card_count: 0, mastered_card_count: 0 }
  const api = createMobileApiStub({
    listChapters: vi.fn().mockResolvedValue([chapter]), searchCards: vi.fn().mockResolvedValue({ total: 0, offset: 0, limit: 20, has_more: false, items: [] }),
    enroll: vi.fn().mockResolvedValue({ scope: 'chapter', created_count: 3, existing_count: 2, card_ids: [1, 2, 3] })
  })
  render(<ChapterPage runtime={runtime(api)} bookId={3} bookName="中医基础理论" />)

  fireEvent.click(await screen.findByRole('button', { name: '加入本章其余卡片' }))
  await waitFor(() => expect(api.enroll).toHaveBeenCalledWith('token', { scope: 'chapter', chapter_id: 8, priority: 60 }))
  expect(await screen.findByText('已加入 3 张卡片')).toBeInTheDocument()
})
