import type { Router } from 'vue-router'

let routerRef: Router | null = null

/** 由 main.ts 在创建 router 后注册，供 axios 拦截器等组件外环境发起导航。 */
export function registerRouter(router: Router): void {
  routerRef = router
}

/** 组件外跳转；router 尚未注册时回退为整页跳转。 */
export function navigateTo(path: string): void {
  if (routerRef) {
    void routerRef.replace(path)
  } else {
    window.location.href = path
  }
}
