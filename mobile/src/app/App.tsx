import { BookOpen, ChartNoAxesColumnIncreasing, Clock3, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'

import { ActivationPage } from '../features/auth/ActivationPage'
import { CardDetailPage, ChapterPage, SubjectsPage } from '../features/catalog/CatalogPages'
import { InsightsPage, WeakTopicsPage, WeeklyTestPage } from '../features/insights/InsightPages'
import { StudySessionPage } from '../features/learning/StudySessionPage'
import { TodayPage } from '../features/learning/TodayPage'
import { MePage, ProfileEditPage } from '../features/profile/ProfilePages'
import { ApiError, type Owner } from '../services/api'
import { withSession } from './session'
import type { AppRuntime } from './runtime'

const navigation = [
  { to: '/today', label: '今日', icon: Clock3 },
  { to: '/subjects', label: '学科', icon: BookOpen },
  { to: '/insights', label: '进度', icon: ChartNoAxesColumnIncreasing },
  { to: '/me', label: '我的', icon: UserRound }
]

type AuthState =
  | { status: 'booting' }
  | { status: 'anonymous' }
  | { status: 'recovery_error'; message: string }
  | { status: 'ready'; owner: Owner }

export function App({ runtime }: { runtime: AppRuntime }) {
  const [auth, setAuth] = useState<AuthState>({ status: 'booting' })
  const [route, setRoute] = useState(readRoute)

  useEffect(() => {
    let cancelled = false
    void resolveStoredAuth(runtime).then((nextAuth) => {
      if (cancelled) return
      setAuth(nextAuth)
      if (nextAuth.status === 'ready' && readRoute() === '/activate') {
        window.location.hash = '/today'
      }
    })
    return () => {
      cancelled = true
    }
  }, [runtime])

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    const onSessionExpired = () => {
      setAuth({ status: 'anonymous' })
      window.location.hash = '/activate'
    }
    window.addEventListener('wenxi:session-expired', onSessionExpired)
    return () => window.removeEventListener('wenxi:session-expired', onSessionExpired)
  }, [])

  useEffect(() => {
    window.__wenxiHandleBack = () => {
      const current = readRoute()
      if (current.startsWith('/study/')) {
        window.dispatchEvent(new Event('wenxi:study-back'))
        return true
      }
      if (isTaskRoute(current)) {
        window.history.back()
        return true
      }
      return false
    }
    return () => { delete window.__wenxiHandleBack }
  }, [route])

  useEffect(() => {
    if (auth.status !== 'ready') return
    const onVisibilityChange = () => {
      if (document.visibilityState !== 'visible') return
      void resolveStoredAuth(runtime).then((nextAuth) => {
        setAuth(nextAuth)
        if (nextAuth.status === 'anonymous') window.location.hash = '/activate'
      })
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [auth.status, runtime])

  async function onActivate(activationCode: string, deviceLabel: string | null) {
    const result = await runtime.api.activate(activationCode, deviceLabel)
    await runtime.sessionStore.write({
      accessToken: result.access_token,
      expiresAt: result.expires_at
    })
    setAuth({ status: 'ready', owner: result.owner })
    try {
      const profile = await runtime.api.getLearningProfile(result.access_token)
      window.location.hash = profile.onboarding_completed_at ? '/today' : '/profile'
    } catch {
      window.location.hash = '/today'
    }
  }

  async function onLogout() {
    const stored = await runtime.sessionStore.read()
    try {
      if (stored) await runtime.api.logout(stored.accessToken)
    } catch {
      // Local logout must still clear credentials when the server is unreachable.
    } finally {
      await runtime.sessionStore.clear()
      setAuth({ status: 'anonymous' })
      window.location.hash = '/activate'
    }
  }

  if (auth.status === 'booting') return <LoadingPage />
  if (auth.status === 'recovery_error') {
    return (
      <RecoveryPage
        message={auth.message}
        onRetry={() => {
          setAuth({ status: 'booting' })
          void resolveStoredAuth(runtime).then((nextAuth) => {
            setAuth(nextAuth)
            if (nextAuth.status === 'ready') window.location.hash = '/today'
          })
        }}
      />
    )
  }
  if (auth.status === 'anonymous') return <ActivationPage onActivate={onActivate} />

  return (
    <div className="app-shell">
      <RouteView route={route} owner={auth.owner} runtime={runtime} onLogout={onLogout} />
      {isTaskRoute(route) ? null : <nav className="tab-bar" aria-label="主要导航">
        {navigation.map((item) => {
          const Icon = item.icon
          return (
            <a
              key={item.to}
              href={'#' + item.to}
              className={'tab-bar__item' + (route === item.to ? ' active' : '')}
            >
              <Icon aria-hidden="true" size={21} strokeWidth={1.9} />
              <span>{item.label}</span>
            </a>
          )
        })}
      </nav>}
    </div>
  )
}

async function resolveStoredAuth(runtime: AppRuntime): Promise<AuthState> {
  const stored = await runtime.sessionStore.read()
  if (!stored || Date.parse(stored.expiresAt) <= Date.now()) {
    await runtime.sessionStore.clear()
    return { status: 'anonymous' }
  }
  try {
    return { status: 'ready', owner: await withSession(runtime, (token) => runtime.api.getMe(token)) }
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await runtime.sessionStore.clear()
      return { status: 'anonymous' }
    }
    return {
      status: 'recovery_error',
      message: error instanceof Error ? error.message : '无法恢复设备会话'
    }
  }
}

function LoadingPage() {
  return (
    <main className="page page--centered" aria-busy="true">
      <section className="state-panel">
        <p className="eyebrow">温习</p>
        <h1>正在连接学习账户</h1>
      </section>
    </main>
  )
}

function RecoveryPage({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <main className="page page--centered">
      <section className="state-panel" aria-labelledby="recovery-title">
        <p className="eyebrow">连接中断</p>
        <h1 id="recovery-title">暂时无法验证设备</h1>
        <p>{message}</p>
        <button className="secondary-button" type="button" onClick={onRetry}>
          重试连接
        </button>
      </section>
    </main>
  )
}

function readRoute() {
  const route = window.location.hash.replace(/^#/, '') || '/activate'
  if (/^\/(study|card|weak)\/\d+$/.test(route)) return route
  if (/^\/book\/\d+(\?.*)?$/.test(route)) return route
  return ['/activate', '/today', '/subjects', '/insights', '/weak', '/weekly', '/me', '/profile'].includes(route)
    ? route
    : '/today'
}

function isTaskRoute(route: string) {
  return route.startsWith('/study/') || route.startsWith('/book/') || route.startsWith('/card/') ||
    route.startsWith('/weak') || route === '/weekly' || route === '/profile'
}

function RouteView({
  route,
  owner,
  runtime,
  onLogout
}: {
  route: string
  owner: Owner
  runtime: AppRuntime
  onLogout: () => Promise<void>
}) {
  if (route.startsWith('/study/')) {
    return <StudySessionPage runtime={runtime} sessionId={Number(route.split('/').pop())} />
  }
  if (route === '/today') return <TodayPage runtime={runtime} />
  if (route === '/subjects') return <SubjectsPage runtime={runtime} />
  if (route.startsWith('/book/')) {
    const [path, query = ''] = route.split('?')
    return <ChapterPage runtime={runtime} bookId={Number(path.split('/').pop())} bookName={new URLSearchParams(query).get('name') ?? ''} />
  }
  if (route.startsWith('/card/')) return <CardDetailPage runtime={runtime} cardId={Number(route.split('/').pop())} />
  if (route === '/insights') return <InsightsPage runtime={runtime} />
  if (route === '/weak') return <WeakTopicsPage runtime={runtime} />
  if (route.startsWith('/weak/')) return <WeakTopicsPage runtime={runtime} targetCardId={Number(route.split('/').pop())} />
  if (route === '/weekly') return <WeeklyTestPage runtime={runtime} />
  if (route === '/profile') return <ProfileEditPage runtime={runtime} />
  if (route === '/me') return <MePage runtime={runtime} owner={owner} onLogout={onLogout} />
  return <TodayPage runtime={runtime} />
}
