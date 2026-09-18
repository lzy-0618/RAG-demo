# Android App 打包与运行说明（含经验总结）

> App 端是独立工程 `frontend-app/`（用 Capacitor 8 套壳），Web 端在 `frontend/`，两边代码各一份、互不引用。
> App 端**只保留登录 + 智能问答**；合同审查、规章制度审查、知识库管理、模板库、合同生成、规章制度生成只存在于 Web 端。

## 0. 一句话经验

套壳本身不难，**难的全在"网络能不能通"和"构建工具链能不能下下来"这两件事上**。业务代码几乎没改，但踩的坑里有三个是纯环境/链路问题，且报错信息都有误导性（详见第 7 节）。

---

## 1. 移动端范围

App 端只有 3 条路由：`/`（重定向到 `/chat`）、`/login`、`/chat`。桌面专属的 6 个页面、它们用到的组件与接口封装都不在 App 工程里，也没有侧栏（`frontend-app/src/App.vue` 只渲染顶部栏）。

拆分前两端共用一份代码，靠 `src/utils/platform.ts` 的 `isApp()`（`Capacitor.isNativePlatform()` 运行时判断）做分支，并给桌面路由标 `meta: { mobile: false }` 由守卫重定向。**拆分后这些平台分支已全部删除**：App 端不再有任何平台判断——它本身就是 App；Web 端也不再引用任何 `@capacitor/*` 包。

## 2. 构建命令

```bash
cd frontend-app

npm run build       # vue-tsc + vite build --mode android（脚本里已固化 android 模式）
npm run cap:sync    # 上一步 + 同步进 android/ 原生工程
npm run cap:run     # 上一步 + cap run android

cd android && ./gradlew assembleDebug   # 只出 APK
```

APK：`frontend-app/android/app/build/outputs/apk/debug/app-debug.apk`

> App 工程的 `build` 脚本已固化为 `--mode android`，在 `frontend-app/` 下直接 `npm run build` 就是正确的 App 构建。（拆分前这个坑是真实存在的：那时 App 与 Web 共用一个 `build`，`build` 走的是 Web 构建，产物同步进 APK 后 API 会打到 `https://localhost` 全部 404。）

## 3. 后端地址

`frontend-app/.env.android`（只被 `--mode android` 读取）：

```
VITE_API_BASE_URL=http://10.0.2.2:8000/api/v1
```

- `10.0.2.2` 是**模拟器指向宿主机回环地址的固定别名**。后端保持监听 `127.0.0.1:8000` 即可，**不需要**改 `0.0.0.0`。
- 模拟器内写 `localhost` / `127.0.0.1` 指向模拟器自己，必连不上。
- **换真机**：改成 Mac 局域网 IP，并在 `CORS_ORIGINS` 与 `network_security_config.xml` 里同步补条目。

## 4. 三处必须的放行（缺一不可）

| # | 位置 | 内容 | 解决什么 |
| --- | --- | --- | --- |
| 1 | `backend/app/core/config.py` 的 `CORS_ORIGINS` | 加 `https://localhost`、`capacitor://localhost` | WebView 页面源是 `https://localhost`，不在白名单则预检直接失败 |
| 2 | `frontend-app/android/app/src/main/res/xml/network_security_config.xml` | `cleartextTrafficPermitted` 放行 `10.0.2.2` | **Android 系统层**禁止明文 HTTP（API 28+） |
| 3 | `frontend-app/capacitor.config.ts` | `android: { allowMixedContent: true }` | **Chromium 层**的 Mixed Content 拦截（见 7.1） |

第 2、3 项是**两层独立的限制**，只做其中一层仍然连不上，这是本次最大的坑。

后端**没有开 `--reload`**，改完 `config.py` 必须手动重启 uvicorn。

自检预检：

```bash
curl -X OPTIONS http://127.0.0.1:8000/api/v1/auth/login \
  -H "Origin: https://localhost" \
  -H "Access-Control-Request-Method: POST" -D - -o /dev/null
# 期望 HTTP 200 且带 access-control-allow-origin: https://localhost
```

## 5. 测试账号

App 登录页下方有「演示账号」区：两张卡片，点卡片本体直接填充表单，右侧按钮把「账号 / 密码」复制进剪贴板。凭据以后端 `.env` 的 `SEED_*` 为准：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 普通用户 | `user01` | `User@2026` |
| 专家（可纠错标注） | `expert` | `Expert@2026` |

是否展示由 `.env.android` 的 `VITE_SHOW_DEMO_ACCOUNTS` 控制。**默认关闭，必须显式写 `true`**：

```
VITE_SHOW_DEMO_ACCOUNTS=true
```

未设该变量、设成空串、设成 `false`，都等于关闭，并且凭据会被打包器 DCE 掉、**不进 JS 产物**
（`import.meta.env.VITE_*` 在构建期被静态替换成字面量，`v-if` 分支折叠后不可达，
只被该分支引用的凭据常量随之被摘除）。实测三种场景：

| 构建 | 标志值 | `dist/assets/*.js` 里有 `Expert@2026` |
| --- | --- | --- |
| `--mode android`（模拟器 / 演示包） | `true` | 有 |
| `--mode production`（发版） | 未设 | **没有** |
| `--mode android` 加环境变量覆盖 | `false` | 没有 |

> 取"默认关闭"是刻意的：变量没设时按最坏打算，避免谁忘了设就静默把凭据带出厂。
> 第一版写成 `!== 'false'`（默认开启）属于 fail-open，已改成 `=== 'true'`。
>
> 终态仍不该把凭据编在前端，应由后端按环境决定是否下发演示账号信息。
> 取舍经过见 `docs/App 端 UI 重做经验总结.md` 第 6 节。

## 6. 环境要求与本机现状

| 项 | 要求 | 本机 |
| --- | --- | --- |
| Node.js | ≥ 22 | v22.21.0 ✅ |
| Android Studio | ≥ 2025.2.1 | 2026.1 ✅ |
| JDK | 由 Android Studio 自带 | JBR 21.0.10 ✅ |
| SDK Platform | API 24+ | android-36 / 36.1 ✅ |
| Build-Tools | `35.0.0`（Capacitor 8 指定） | 35.0.0 / 36.0.0 ✅ |

`ANDROID_HOME` 未设置也能构建——`android/local.properties` 里的 `sdk.dir` 已足够。

---

## 7. 踩坑记录（重点）

### 7.1 ⭐ Mixed Content：最隐蔽的一层拦截

**现象**：模拟器里点登录毫无反应，logcat 里：

```
Mixed Content: The page at 'https://localhost/login?redirect=/chat' was loaded over HTTPS,
but requested an insecure XMLHttpRequest endpoint 'http://10.0.2.2:8000/api/v1/auth/login'.
This request has been blocked; the content must be served over HTTPS.
```

**原因**：Capacitor 默认 `androidScheme: 'https'`，WebView 页面源是 `https://localhost`。从 https 页面发 http 请求，被 **Chromium 的 Mixed Content 策略**拦截。

**关键认知**：`network_security_config.xml` 管的是 **Android 系统层**的明文策略，**管不到 Chromium 这一层**。两者是独立的，配了一个不代表另一个也通了。

**解决**：`capacitor.config.ts` 里开 `android: { allowMixedContent: true }`（Capacitor 的 `Bridge.java` 会把它设为 `MIXED_CONTENT_ALWAYS_ALLOW`）。

**验证生效的标志**：logcat 措辞从 `...has been blocked; the content must be served over HTTPS`（拦截）变成 `...should also be served over HTTPS`（放行但告警）。

> 官方文档标注该项"不用于生产"。后端上 HTTPS 后应移除。

### 7.2 ⭐ Gradle 发行版下载被限速到不可用

`services.gradle.org` 直连实测只有 **175 B/s**（小文件还行，一上量就掐）。而 wrapper 的 `networkTimeout=10000`（10 秒）太短，**且 wrapper 不支持断点续传**——每次重试都从 0 开始，必然反复失败。

**绕过办法**：用镜像下载后手工放到 wrapper 期望的目录，**不必改仓库里的 `distributionUrl`**：

```bash
d=~/.gradle/wrapper/dists/gradle-8.14.3-all/10utluxaxniiv4wxiphsi49nj
cd "$d"
# 腾讯云镜像实测 2 MB/s，比官方快一万倍
curl -L -C - -o gradle-8.14.3-all.zip \
  https://mirrors.cloud.tencent.com/gradle/gradle-8.14.3-all.zip
# 哈希仍以官方为准（腾讯云不提供 .sha256；取官方值要加 -L 跟随 301）
shasum -a 256 gradle-8.14.3-all.zip
curl -sSL https://services.gradle.org/distributions/gradle-8.14.3-all.zip.sha256
unzip -q gradle-8.14.3-all.zip && touch gradle-8.14.3-all.zip.ok
```

`.ok` 标记文件是 wrapper 判断"装好了"的依据，**必须建**。

### 7.3 ⭐ SDK 组件缺失 + 空目录陷阱

首次 `./gradlew assembleDebug` 报：

```
Failed to install the following SDK components:
      build-tools;35.0.0 Android SDK Build-Tools 35
      platforms;android-36 Android SDK Platform 36
```

Capacitor 8 的 `variables.gradle` 要 `android-36` + build-tools `35.0.0`，而机器上原本只有 `android-36.1` + build-tools `36.0.0`。

**陷阱**：Gradle 的自动安装会**失败但留下空目录**，导致下一次报错信息变模糊，很难判断到底是"装了没装全"。

**绕过办法**：直接从 Google 仓库下 zip 手工解包。URL 可从 `https://dl.google.com/android/repository/repository2-3.xml` 查。

```bash
# build-tools：zip 顶层目录叫 android-15，解压后必须重命名为版本号
curl -o bt35.zip https://dl.google.com/android/repository/build-tools_r35_macosx.zip
unzip -q bt35.zip -d /tmp/bt && mv /tmp/bt/android-15 ~/Library/Android/sdk/build-tools/35.0.0

# platform：zip 顶层就是 android-36，直接解压
curl -o p36.zip https://dl.google.com/android/repository/platform-36_r02.zip
unzip -q p36.zip -d ~/Library/Android/sdk/platforms/
```

装完用 `sdkmanager --list` 能看到它们即算成功。

### 7.4 ⭐ `yes | sdkmanager --install` 会卡死

用 `yes |` 自动接受许可会让 `sdkmanager` **僵住且不报错**——表现为无 java 子进程、无网络连接、CPU 时间 0。这是最浪费时间的一个坑，一开始误以为"下载慢"。

许可证其实早已接受（`~/Library/Android/sdk/licenses/android-sdk-license` 存在），**直接用 `curl` 下 zip 更可靠**。`avdmanager` 不受影响，正常可用。

### 7.5 系统镜像与模拟器

- 镜像 `system-images;android-36;google_apis;arm64-v8a` 约 **1.87 GB**，直连 `dl.google.com` 约 1.6–2.4 MB/s，约 15 分钟。
- `dl.google.com` **直连比走本地代理快**，下载时加 `--noproxy '*'`。
- 解压后约 4.3 GB（`system.img` 单个 4.1 GB），注意磁盘空间。
- 建 AVD：

```bash
avdmanager create avd -n RAG_demo_API36 \
  -k "system-images;android-36;google_apis;arm64-v8a" -d medium_phone
~/Library/Android/sdk/emulator/emulator -avd RAG_demo_API36 -no-boot-anim -gpu auto
```

本机 `avdmanager list device` 里**没有 pixel_* 档位**，用 `medium_phone` 即可。

### 7.6 命令行操作模拟器的小经验

- `adb shell input text` **只支持 ASCII**，中文输入不了。测中文得靠剪贴板或真机。
- `input text` 里的**空格必须写成 `%s`**，否则只有第一个词会落进输入框：

  ```bash
  adb shell input text 'travel policy'     # ✗ 输入框里只剩 "travel"
  adb shell input text 'travel%spolicy'    # ✓
  ```

- **别拿 `uiautomator dump` 的 `bounds` 去点**。dump 用来**断言页面内容**很好用（WebView 暴露无障碍节点，
  中文文本、`aria-label` 都能读到），但它的坐标和帧缓冲不是同一个空间：本例里账号输入框报的是
  `[181,729][979,811]`，而 `screencap` 里它真实位于 `y 862..981`，**比例和原点都不一样**，直接拿来 `input tap` 必然点错。

  稳妥的定位办法是**从截图里量**。macOS 自带的 `sips --cropOffset` 不可靠
  （`-c 120 1080 --cropOffset 2280 0` 会返回整页），用 PIL：

  ```python
  from PIL import Image
  Image.open("shot.png").crop((l, t, r, b)).save("crop.png")
  ```

  再写个"沿某一列扫颜色、输出连续色带"的小脚本，就能把按钮中心定位到几像素内——例如登录按钮是
  登录页上唯一的大块朱红 `#b3342a`，一测就知道它在 `y 1326..1451`（中心 `540,1388`）。

- **软键盘弹起与否会整体重排**，同一个按钮的 y 坐标会变，而且**变化量不小**。
  实测问答页输入区底边：键盘收起时在 `y≈2296`，弹起时上移到 `y≈1475`，位移约 820px
  （≈313 CSS px，基本就是 Gboard 占掉的高度）。登录页的表现不同——它是整页滚动，
  登录按钮从 `y 1326..1451` 上移到 `1174..1299`，只移了约 150px。

  所以每次点击前先确认键盘状态，并且要在**同一状态**下量坐标。两个细节：
  - `input keyevent 111`（ESC）**不一定能收起键盘**，用 `keyevent 4`（BACK）才可靠；
  - 键盘没收起时，你按"无键盘"算出的 y 坐标会落到键盘按键上（我曾因此往账号框里多打了一个 `e`）。

- 用 `pm clear` 清数据时**先 `am force-stop`**，否则清完再启动出来的状态可能和预期对不上（见 7.8）：

  ```bash
  adb shell am force-stop com.baozhishen.app && adb shell pm clear com.baozhishen.app
  ```

- 解析 dump 结果时正则要写对——我因为 grep 模式写错，一度误判"输入没落进去"，实际早就填好了。

### 7.7 别被管道掩盖退出码

```bash
./gradlew assembleDebug | tail -30    # ← $? 是 tail 的，永远是 0
```

我第一次就是这样把 `BUILD FAILED` 读成了"构建成功"。**改成重定向到文件再取 `$?`**：

```bash
./gradlew assembleDebug > /tmp/build.log 2>&1; echo "EXIT=$?"; tail -30 /tmp/build.log
```

同理，`if grep ... | head` 测的是 `head` 的退出码，恒为真——会误报。判断有无命中要用 `grep -q` 或数数。

### 7.8 未复现的可疑现象：清数据后首次点击疑似"自动登录"

**现象**：一次 `pm clear` + `am start` 之后（**没有**先 force-stop），截图里登录页正常显示；
随后我只发了**一次**点击（按截图量出的坐标，命中的是「普通用户」卡片的复制按钮），
但下一张截图显示应用**已登录为 `expert`**，并且聊天页里已经发出了一条示例问题
（"差旅报销标准是什么？"）。这一状态此前从未出现过，不可能是陈旧帧。

**复现结果**：重复同样的单点操作**未复现**；加上 `am force-stop` 后，登录、填充、复制、
流式问答全流程一次通过。

**已排除的代码路径**：登录页没有任何"自动提交"通路——表单是 `@submit.prevent`，
两张演示卡片的两个按钮都是 `type="button"` 且位于 `<el-form>` **之外**，
`el-button` 的默认 `native-type` 是 `button`（不会触发表单提交）。两个输入框上的
`@keyup.enter` 是唯一的隐式提交入口，而那需要先有凭据被填进去。

**结论**：倾向于模拟器侧的输入投递异常，未能定位到根因。日后再出现时，优先看这一条。

> **排查时踩的坑**：我一度用 `grep -c api_jwt.py:147 /tmp/uvicorn-app.log` 当"登录次数"计数器，
> 得出"发生了两次登录"的结论——这是错的。Python `warnings` 默认对**同一处**告警只打一次，
> 计数恒为 1；而且该 uvicorn 没开 access log，请求行根本不会落盘。
> 要可靠地数请求，自己加中间件或给 uvicorn 开 `--access-log`。

---

## 8. 从零到跑起来的完整顺序

以下命令都在 `frontend-app/` 内执行（该工程已存在，这里记录的是当初从零搭建的过程）：

1. `npm i @capacitor/core@8 @capacitor/android@8 @capacitor/browser@8 && npm i -D @capacitor/cli@8`
2. 写 `capacitor.config.ts`（含 `android.allowMixedContent: true`）
3. `npx cap add android`
4. 建 `network_security_config.xml` 并挂到 `AndroidManifest.xml` 的 `<application>`
5. 建 `.env.android`，把 `build` 脚本固化为 `--mode android`，加 `cap:sync` / `cap:run`
6. 后端 `CORS_ORIGINS` 加 `https://localhost` 并**重启后端**
7. `npm run cap:sync`
8. `cd android && ./gradlew assembleDebug`
9. `adb install -r app-debug.apk`
10. 登录验证

## 9. 验证状态

| 项 | 状态 |
| --- | --- |
| 工程拆分 | ✅ Web（`frontend/`）与 App（`frontend-app/`）两份独立代码，无共享目录、互不引用 |
| App 工程独立可构建 | ✅ `npm install` → `npm run build` → `cap sync` → `assembleDebug` 全链路通过 |
| App 端平台分支清理 | ✅ 无 `isApp()`、无 `meta.mobile`、无桌面页面残留 |
| Web 端去 Capacitor | ✅ 依赖、`android/`、`capacitor.config.ts`、`.env.android` 均已移除，`npm run build` 通过 |
| APK 构建 | ✅ 4.8 MB，`com.baozhishen.app`，应用名「宝智审」 |
| 内部资源 | ✅ 前端产物、`10.0.2.2` 地址、`networkSecurityConfig` 均正确打入 |
| Web 版未受影响 | ✅ `npm run build` 产物不含 `10.0.2.2`，API 仍为相对路径，6 个桌面页面齐备 |
| 模拟器启动 + 安装 | ✅ API 36 / arm64-v8a，33 秒开机 |
| 登录页渲染 | ✅ 印章 Logo + 字标，无键盘遮挡 |
| 登录成功 | ✅ 进入「智能问答」，抬头显示 `user01` / 普通用户 / 退出 |
| 侧栏隐藏 | ✅ App 内无侧栏 |
| **拆分后重装回归** | ✅ 已复验——`force-stop` + `pm clear` + 重装后，登录与问答全链路通过 |
| **流式问答** | ✅ 已复验——`fetch` + `ReadableStream` 在 WebView 正常，含依据来源与专家标注入口 |

### 9.1 登录页与问答页 UI 重做（本轮）

| 项 | 状态 |
| --- | --- |
| 登录页去掉纯白面板、露出纸色纸纹 | ✅ |
| 印章 Logo（`BrandMark.vue`：内联 SVG 方印 + 宋体「宝」+ 字标 + 副标题） | ✅ |
| 表单 48px 触控高度、内联图标、朱红聚焦环、16px 字号 | ✅ |
| 演示账号卡片：点卡片填充 / 按钮复制 | ✅ 两者都实测通过 |
| 复制内容验证 | ✅ 粘贴回输入框得到 `user01 / User@2026`，`navigator.clipboard` 在 WebView 可用 |
| 软键盘弹起不裁登录按钮 | ✅ 页面滚动，按钮完整上移（`y 1326..1451` → `1174..1299`） |
| 顶栏：印章小标 + 收紧间距 + 退出降为墨色次级 | ✅ |
| 问答卡片改通栏 + 左侧引注线，流式时转朱红 | ✅ |
| 回答内 `h1-h4` 字号收敛（原来会撑出 25px 宋体大标题） | ✅ |
| 依据来源改账目式列表（等宽编号 + 文档名 + 段落/相似度） | ✅ |
| 回答一键复制 | ✅ 复制的是 `innerText` 纯文本，markdown 符号已渲染掉 |
| 输入区重做（圆角框 + 自动增高 + 圆形朱红发送按钮） | ✅ |
| 停止生成 | ✅ 提问 1 秒后点停止，追加「（已停止生成）」 |
| 贴底才自动跟随 + 「回到底部」浮钮 | ✅ 上翻不再被拽回；浮钮在白色卡片上改为墨色底 |
| 首屏示例问题 | ✅ 三个标签，点一下直接发出 |
| 新建会话重置（清空输入、恢复示例问题） | ✅ |
| 专家「标注纠错」入口 | ✅ 仅 `expert` 角色可见 |

## 10. 尚未做

- **应用图标与启动图**：仍是 Capacitor 默认的蓝色占位图标和默认 splash，桌面上不像「宝智审」。
  要改的是 `android/app/src/main/res/` 下的多密度 PNG + 自适应图标 XML，属原生资源改造，未包含在 UI 重做里。
- 外链跳系统浏览器（`Browser.open`）的运行时验证
- 401 不白屏的运行时验证（`401 → 清 token → 跳登录` 这条路径本轮没有构造出来）
- Word 产物下载桥接（模板库/生成页不在移动端，`<a download>` 在 WebView 失效的问题暂不涉及）
- 审查页与生成页的移动布局适配（这两个页面本来就不在 App 端）
- release 签名、上架
- 真机局域网访问与后端 HTTPS
- App 工程内的死代码：`src/styles/patterns.css`、`src/api/knowledge.ts`、`highlight.js` 依赖
  ——都是拆分时从 Web 端带过来的，App 里没有任何引用
- 回答里「依据来源」会出现两次：模型自己写了一段，App 末尾又追加了检索证据块。
  两块内容性质不同（叙述性引用 vs 检索命中段落），但标题同名，措辞上可以区分开
