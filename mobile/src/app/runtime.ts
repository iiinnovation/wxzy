import { readApiBaseUrl } from '../config'
import { createPlatformSessionStore } from '../platform/secureSession'
import type { SessionStore } from '../platform/sessionStore'
import { createApiClient, type MobileApi } from '../services/api'

export interface AppRuntime {
  api: MobileApi
  sessionStore: SessionStore
}

export function createBrowserRuntime(): AppRuntime {
  return {
    api: createApiClient({ baseUrl: readApiBaseUrl() }),
    sessionStore: createPlatformSessionStore()
  }
}
