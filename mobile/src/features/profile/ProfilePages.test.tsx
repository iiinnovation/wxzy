import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { AppRuntime } from '../../app/runtime'
import { createMemorySessionStore } from '../../platform/sessionStore'
import type { LearningProfile } from '../../services/api'
import { createMobileApiStub } from '../../test/mobileApiStub'
import { MePage, ProfileEditPage } from './ProfilePages'

const profile: LearningProfile = { id: 1, user_id: 1, goal_type: 'daily_learning', target_date: null, daily_minutes: 20, study_days: [true, true, true, true, true, false, false], desired_retention: 0.9, new_card_ceiling: 5, subject_priorities: { 基础理论: 4 }, initial_self_assessment: { 基础理论: 3 }, onboarding_completed_at: '2026-07-01T00:00:00Z', created_at: '2026-07-01T00:00:00Z', updated_at: '2026-07-27T10:00:00Z', display_name: '学习者', timezone: 'Asia/Shanghai' }
const owner = { id: 1, status: 'active', display_name: '学习者', timezone: 'Asia/Shanghai' }
function runtime(api: ReturnType<typeof createMobileApiStub>): AppRuntime { return { api, sessionStore: createMemorySessionStore({ accessToken: 'token', expiresAt: '2099-01-01T00:00:00Z' }) } }

test('saves the complete profile with optimistic concurrency metadata', async () => {
  const updated = { ...profile, daily_minutes: 30, updated_at: '2026-07-27T11:00:00Z' }
  const api = createMobileApiStub({ getLearningProfile: vi.fn().mockResolvedValue(profile), updateLearningProfile: vi.fn().mockResolvedValue(updated) })
  render(<ProfileEditPage runtime={runtime(api)} />)

  const minutes = await screen.findByLabelText('每日分钟')
  fireEvent.change(minutes, { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: '保存档案' }))
  await waitFor(() => expect(api.updateLearningProfile).toHaveBeenCalled())
  expect(vi.mocked(api.updateLearningProfile).mock.calls[0][1]).toMatchObject({ expected_updated_at: profile.updated_at, daily_minutes: 30, onboarding_completed: true })
  expect(await screen.findByText('档案已保存')).toBeInTheDocument()
})

test('lists sessions and revokes another active device', async () => {
  const api = createMobileApiStub({ getLearningProfile: vi.fn().mockResolvedValue(profile), listSessions: vi.fn().mockResolvedValue({ items: [{ id: 2, device_label: '微信', created_at: '2026-07-01T00:00:00Z', expires_at: '2099-01-01T00:00:00Z', revoked_at: null, status: 'active', current: false }] }), revokeSession: vi.fn().mockResolvedValue(undefined) })
  render(<MePage runtime={runtime(api)} owner={owner} onLogout={vi.fn()} />)

  fireEvent.click(await screen.findByRole('button', { name: '撤销 微信' }))
  await waitFor(() => expect(api.revokeSession).toHaveBeenCalledWith('token', 2))
  expect(await screen.findByText('设备会话已撤销')).toBeInTheDocument()
})
