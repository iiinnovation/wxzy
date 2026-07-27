/// <reference types="vite/client" />

declare global {
  interface Window {
    __wenxiHandleBack?: () => boolean
  }
}

export {}
