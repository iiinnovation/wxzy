export interface StoredSession {
  accessToken: string
  expiresAt: string
}

export interface SessionStore {
  read(): Promise<StoredSession | null>
  write(session: StoredSession): Promise<void>
  clear(): Promise<void>
}

export function createMemorySessionStore(initial: StoredSession | null = null): SessionStore {
  let current = initial
  return {
    async read() {
      return current
    },
    async write(session) {
      current = { ...session }
    },
    async clear() {
      current = null
    }
  }
}
