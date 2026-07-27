import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'xin.luoandlt.wxzy',
  appName: '温习',
  webDir: 'dist',
  plugins: {
    SystemBars: {
      insetsHandling: 'css',
      style: 'LIGHT',
      hidden: false
    }
  },
  server: {
    androidScheme: 'https'
  }
}

export default config
