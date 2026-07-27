const developmentApiBase = 'http://127.0.0.1:8000'

export function readApiBaseUrl(environment = import.meta.env): string {
  const configured = environment.VITE_API_BASE_URL?.trim()
  if (configured) return configured.replace(/\/+$/, '')
  if (environment.PROD) {
    throw new Error('VITE_API_BASE_URL is required for production builds')
  }
  return developmentApiBase
}
