import { Capacitor, registerPlugin } from '@capacitor/core'

import { createMemorySessionStore, type SessionStore, type StoredSession } from './sessionStore'

interface SecureSessionPlugin {
  read(): Promise<Partial<StoredSession>>
  write(session: StoredSession): Promise<void>
  clear(): Promise<void>
}

const nativePlugin = registerPlugin<SecureSessionPlugin>('SecureSession')

export function createPlatformSessionStore(): SessionStore {
  return Capacitor.isNativePlatform()
    ? createNativeSessionStore(nativePlugin)
    : createMemorySessionStore()
}

export function createNativeSessionStore(plugin: SecureSessionPlugin): SessionStore {
  return {
    async read() {
      const value = await plugin.read()
      return value.accessToken && value.expiresAt
        ? { accessToken: value.accessToken, expiresAt: value.expiresAt }
        : null
    },
    write(session) {
      return plugin.write(session)
    },
    clear() {
      return plugin.clear()
    }
  }
}
