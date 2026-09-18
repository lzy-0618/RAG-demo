# frontend-app（Vue 3 + Vite + TypeScript + Element Plus + Pinia + Capacitor 8）

企业合规智能平台**安卓 App 端**，用 Capacitor 套壳，产物为 APK。

> Web 端是另一个独立工程 `frontend/`，两端代码不共享——这里改什么都不会影响 Web，反之亦然。
> 打包踩坑、环境要求、三处网络放行等完整说明见 `docs/Android App 打包与运行说明.md`。

## 范围

只保留两条链路：**登录** + **智能问答**（含专家就地标注）。合同审查、规章制度审查、知识库管理、模板库、合同生成、规章制度生成只存在于 Web 端，不在本工程内。

## 本地运行

```bash
npm install
npm run build       # vue-tsc 类型检查 + vite build --mode android
npm run cap:sync    # 上一步 + 同步进 android/ 原生工程
npm run cap:run     # 上一步 + 在设备/模拟器上运行

cd android && ./gradlew assembleDebug   # 只出 APK
```

APK 产物：`android/app/build/outputs/apk/debug/app-debug.apk`

`build` 脚本已固化为 `--mode android`，所以在**本目录**下 `npm run build` 就是正确的 App 构建。

## 后端地址

`.env.android`（只被 `--mode android` 读取）：

```
VITE_API_BASE_URL=http://10.0.2.2:8000/api/v1
```

`10.0.2.2` 是模拟器指向宿主机回环地址的固定别名。换真机调试要改成 Mac 的局域网 IP，并同步在 `backend/app/core/config.py` 的 `CORS_ORIGINS` 与 `android/app/src/main/res/xml/network_security_config.xml` 里补条目。

## 目录约定

```
src/
├── api/         # axios 封装（http/auth/chat/correction/knowledge）
├── views/       # 登录、智能问答
├── stores/      # Pinia（user：token 与登录态）
├── router/      # /login、/chat 与登录守卫
├── styles/      # 设计令牌与 Element Plus 改皮
└── main.ts
android/         # Capacitor 原生工程，一般不需要手改
```

## 与 Web 端的关系

两端各有一份 `api/`、`stores/`、`styles/`。后端接口变更时需要**各自改一份**——这是为换取两端可独立定制而接受的代价。不要引入共享包，也不要重新加入 `isApp()` 之类的运行时平台分支。
