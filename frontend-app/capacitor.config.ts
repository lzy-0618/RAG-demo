import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.baozhishen.app',
  appName: '宝智审',
  webDir: 'dist',
  android: {
    // WebView 的页面源是 https://localhost，向 http 后端发请求会额外被 Chromium 的
    // Mixed Content 拦截——这与 Android 系统层的明文策略是两层独立限制，
    // network_security_config 只管后者。仅开发期连本地 http 后端需要；后端上 HTTPS 后应移除。
    allowMixedContent: true,
  },
}

export default config
