import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router from './router'
// 顺序有意义：先 Element Plus 出厂样式，再叠加本项目令牌与改皮，后者需要覆盖前者
import './styles/tokens.css'
import './styles/base.css'
import './styles/element.css'
import './styles/patterns.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
