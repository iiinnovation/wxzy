import { ApiError, type SessionToken } from '../services/api'
import type { AppRuntime } from './runtime'

const REFRESH_WINDOW_MS = 5 * 60 * 1000

export async function getAccessToken(runtime: AppRuntime, forceRefresh = false): Promise<string> {
  const stored = await runtime.sessionStore.read()
  if (!stored) throw new ApiError(401, 'SESSION_MISSING', '设备会话已失效，请重新激活')

  const expiresAt = Date.parse(stored.expiresAt)
  if (!forceRefresh && Number.isFinite(expiresAt) && expiresAt - Date.now() > REFRESH_WINDOW_MS) {
    return stored.accessToken
  }

  try {
    const refreshed = await runtime.api.refresh(stored.accessToken)
    await persistSession(runtime, refreshed)
    return refreshed.access_token
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) await expireSession(runtime)
    throw error
  }
}

export async function withSession<T>(
  runtime: AppRuntime,
  operation: (accessToken: string) => Promise<T>
): Promise<T> {
  const token = await getAccessToken(runtime)
  try {
    return await operation(token)
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error
    const refreshedToken = await getAccessToken(runtime, true)
    return operation(refreshedToken)
  }
}

export async function refreshStoredSession(runtime: AppRuntime): Promise<SessionToken | null> {
  const stored = await runtime.sessionStore.read()
  if (!stored) return null
  const refreshed = await runtime.api.refresh(stored.accessToken)
  await persistSession(runtime, refreshed)
  return refreshed
}

async function persistSession(runtime: AppRuntime, session: SessionToken) {
  await runtime.sessionStore.write({
    accessToken: session.access_token,
    expiresAt: session.expires_at
  })
}

async function expireSession(runtime: AppRuntime) {
  await runtime.sessionStore.clear()
  window.dispatchEvent(new Event('wenxi:session-expired'))
}
