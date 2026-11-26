# 发布工作流

本文规定改动提交与发布步骤，措辞、条目与排版见 [中文措辞](writing-style.md#中文措辞) 与 [条目与排版](writing-style.md#条目与排版)。

## 总流程（发布日按序执行）

```text
功能提交若干（改动同步记 Unreleased）
  → 发布定稿提交（CHANGELOG 归段 + 版本号）
  → 构建 zip 并本地实测
  → 附注 tag 并推送
  → 发布 release
  → 版本页校验收尾
```

## 五项闸门（提交与发布前跑齐）

```powershell
.venv\Scripts\python.exe devtools\gates.py
```

- 一条命令跑齐五步，任一步红即整体退一，红步下带最多 30 行原始输出，只重跑点名的步用 `--only` 接步名，可多次，候选 `ruff`／`pyright`／`imports`／`style`／`pytest`。
- 源码与用例目标按挂载现场算，含本体三棵树与各挂载子仓声明的目录。
- 绿的标准：ruff format 与 check 通过、pyright 0 errors、契约 0 broken、扫描器 0 硬性、pytest 全过。
- pyright 用开发依赖带的 node，`devtools/pyproject.toml` 声明 `pyright[nodejs]`，`uv sync --all-packages` 后即齐，不需要另外装 Node.js，扫描器分节、待核基线与豁免见 [规范扫描器](style-checker.md)，用例见 [测试](testing.md)，构建见 [打包教程](packaging.md)。

## 日常与定稿

- 一轮改动五项闸门全绿即分组 commit，本地攒着不 push，半成品不入库，push、tag 只在发布日动。
- 未 push 期间随便整历史，已 push 的笔日常不改写，改动折回原笔，同主题并笔、reword 修措辞，CHANGELOG 跟行为改动一起交，整完验 `git diff 整备前位置 HEAD` 为空。
- 历史整备期允许一次全量重写，条件是 release 附件与 zip 不动、全部 tag 删旧重打并钉 tagger 日期、镜像仓重灌、`git diff 重写前位置 HEAD` 为空。

## 子仓供件

- 挂载、日常改动、更新与摘掉见 [挂载子仓](development.md#挂载子仓)，wheel 构建见 [子仓构建](packaging.md#子仓构建)，分层契约与发布物打包归本体。
- 子仓跑格式、类型、规范、用例四项检查，目标由闸门按挂载现场算，版本号以 `pyproject.toml` 的 `[project].version` 为单源，tag、wheel 文件名与本体读到的版本都从它取。
- 适配器发版只在子仓，本体发布链不含适配器版本：
  - release 附件只放 wheel，正文不写下载直链，直链与指纹取 GitHub 记在 wheel 附件上的值，release 建完即定稿，旧版附件不撤。
  - 正文标题行写 `🐳 仓名-v版本号`，其下空一行直接铺条目，不带段名行，末条写"要求接口包 `finshin-sdk>=X1.Y1.Z1,<X2.Y2.Z2`。"，随版本只换数字。
- 在线目录由本体 Pages 工作流按账号下各仓声明聚合，与版本页一起部署，子仓单独发版后最长等本体一次 push 或每日定时重建，"工作区干净"算本体与每只子仓。

## CHANGELOG

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，条目一律 `- **加粗要点**：说明`。

### 版本段

- 分节固定，带 emoji，一个版本段内按此序排列，缺项不占位：
  - `### ⚠️ Breaking Changes` → `### ✨ Added` → `### 🔧 Changed` → `### 🐛 Fixed` → `### 🗑️ Removed`
  - `### 📝 Planned` 只出现在 `## [Unreleased]` 里，恒排最前。
- `## [Unreleased]` 恒在顶部，标题行只写这一句，发布时把内容归入 `## [X.Y.Z] - YYYY-MM-DD`，日期为发布当天，Planned 不过期。
- 预发布线：`devN` 段随每次预发布实录，发正式号时新增正式段，按用户可感知的功能域写本版变化，不复述 dev 明细。
- 正式号归段后删除该条线所有 `devN` 段，只留正式号，归段前不得提前删，末个 dev 段之后未单独发号的收敛改动直接写入正式段，不倒造无产物的 dev 段。

### 写什么

- 只写关键条目，琐碎改动一笔带过或不写，加了又删的功能不留痕迹，增与删的条目一起清。
- 用户视角写行为，不写实现细节，内部重构只写改了哪些共用关系，主题名按功能域起，层级、标点与反引号见 [条目与排版](writing-style.md#条目与排版)、[行尾与分号](writing-style.md#行尾与分号) 与 [引用与代码标识](writing-style.md#引用与代码标识)，已发布版本段日常不回改，Unreleased 随新规整理，历史整备期按现行规范全量重写属例外。

## Commit

### 标题与页脚

- 标题采用 Conventional Commits 与中文标题的 `type(scope): 主题`，50 字符内，首字母小写，模板见 [.gitmessage](../.gitmessage)，正文行形状见 [条目与排版](writing-style.md#条目与排版)，页脚用于关联 Issue，破坏性变更写正文，不写页脚标记。

### 类型与归段

| type | 用途 | CHANGELOG 归段 |
| :--- | :--- | :--- |
| feat | 纯新增用户可感知的行为 | Added |
| change | 改掉既有的用户可感知行为 | Changed |
| fix | 纠正与既定期望相违的行为 | Fixed |
| remove | 删掉用户可感知的行为或产物 | Removed |
| breaking | 主体就是让用户动手 | Breaking Changes |
| refactor | 内部重整，用户可感知行为不变 | Changed |
| perf | 只改耗时与资源占用，功能与观感不变 | Changed |
| docs / style / test | 只改文档 / 格式 / 用例 | 不记 |
| build | 版本与打包定稿 | 不记 |
| revert | 回退已推送的改动 | 跟着被回退的那两条一起清 |

- 第一刀按用户能不能感知分，一笔只写一个 type，取主题主导那面，其余面只进 CHANGELOG 对应段，版本号档见 [版本号（semver）](#版本号semver)，版本段见 [版本段](#版本段)。

- fix 与 change：已写下的期望被违反是 fix，没违反只是改主意是 change，remove 与 change：做完用户少一样能用的东西或少一个产物是 remove。
- perf 与 change：观感与功能变化归 change，perf 只指耗时、内存与体积，breaking 只在主体是"用户必须动手"时用，既新增又要动手的笔按新增定 type。

### scope 与分组

- scope 用模块域小写，取它改的那块的名字，`docs`、`style`、`test`、`build` 可省，其余必带，一组提交为一个主题，不按文件凑数，同主题跨层合为一组，发布定稿单独一笔 `build(release): vX.Y.Z 发布定稿`，只含 CHANGELOG 归段与 pyproject 版本号。

## 构建 zip

- 定稿提交后本地构建，全程只构建这一次，命令、自检与用户路径实测见 [打包教程](packaging.md)，测试与上传使用同一次构建的 zip，任一实测失败都不许发布。

## Tag

附注 tag，注解格式固定：

```powershell
git tag -a vX.Y.Z -m "Release vX.Y.Z: 关键词一，关键词二，关键词三"
git push origin main vX.Y.Z
```

- 摘要用逗号分隔的功能关键词，3 个上下，打在发布定稿提交上，不追打历史提交，重写历史后按定稿笔标题重打全部 tag。

## 版本号（semver）

| 场景 | 升位 |
| :--- | :--- |
| 正式定版 | 1.0.0 |
| 定版前公开试用 | 预发布号 `X.Y.Z-<阶段>.N`（如 `1.0.0-alpha.1`），tag 与产物名全程带后缀 |
| 纯修复 | patch（1.0.0 → 1.0.1） |
| 有新功能 | minor（1.0.0 → 1.1.0） |
| 破坏性行为变更 | major（1.0.0 → 2.0.0） |

- 预发布阶段取 `alpha`、`beta`、`rc` 之一，写作 `X.Y.Z-<阶段>.N`，实录段再缀 `.devM`，写作 `X.Y.Z-<阶段>.N.devM`，三种串在 CHANGELOG 版本段、tag、产物名与 pyproject 版本号全程同形，只差 tag 与产物名前那个 `v`。

## Release

### 操作顺序

发布在 GitHub 网页端操作，按序：

- 进仓库 [Releases](https://github.com/FinshinLabs/FinshinImpact/releases)，Draft a new release，选推送上来的 tag `vX.Y.Z`。
- 填正文，形状见 [首发正文](#首发正文发布日带-zip) 与 [旧版收敛](#旧版收敛不带-zip)，选上一版 tag 并点 **Generate release notes**，再 Publish。

### 正文与比较链接

- 正文条目从 CHANGELOG 对应版本段提炼改写，段名行与下载直链行不带句号，比较链接由 Generate release notes 生成，形状 `**Full Changelog**: https://github.com/FinshinLabs/FinshinImpact/compare/v<上一版>...v<X.Y.Z>`。
- 正式号取上一个**正式号**，覆盖整条预发布线，dev 取紧邻上一个号，只覆盖这一次增量，首版没有上一版 tag，比较链接那行写本版 tag 的提交链接。

### 首发正文（发布日，带 zip）

```text
🐳 FinshinImpact-vX.Y.Z

- 国内加速1：https://gh-proxy.com/https://github.com/FinshinLabs/FinshinImpact/releases/download/vX.Y.Z/FinshinImpact-vX.Y.Z.zip
- 国内加速2：https://ghproxy.net/https://github.com/FinshinLabs/FinshinImpact/releases/download/vX.Y.Z/FinshinImpact-vX.Y.Z.zip

变化
- 条目一（用户视角，2~5 条）。
- 条目二。

注意（仅升级路径或行为有特殊约束时写，无则整段省略）
- 只写事实与用户需要的动作，一句一条，禁口语、修辞、情绪化措辞。
- 有破坏性变更时提示用户如何操作。
```

- 正式号各留一条 release，长期保留，dev 段 release 只在预发布期挂着供当时下载，正式号发出时把各 dev 变化汇总进正式号，再删 dev 的 release 条目，汇总写法与 CHANGELOG 正式段同一口径。
- ⚠️ 删的是 release 条目，tag 一律保留，正式号之间按 [旧版收敛](#旧版收敛不带-zip) 处理。

### 旧版收敛（不带 zip）

被取代的旧版只删发布包、留条目，正文不写下载行，GitHub 每条 release 页自动挂 `Source code (zip)` 与 `Source code (tar.gz)`：

```text
🐳 FinshinImpact-vX.Y.Z

变化
- 条目一。
- 条目二。

注意
- 条目一。

**Full Changelog**: https://github.com/FinshinLabs/FinshinImpact/compare/v<上一版>...vX.Y.Z
```

⚠️**删发布包不可逆**。

### prerelease 与 latest

- 预发布号一律勾 `Pre-release`，正式版新发布默认勾选 `Latest`。

## 版本页同步（发布最后一步）

Release 发布完成不等于升级链生效，在线版本页是启动器检查更新的唯一来源。

- 主仓 workflow 随 push `main` 部署版本页与在线目录，无需手动覆盖推送，闭环判据是跑 `python packaging\build.py --check`，"在线版本页"那一行显示新版本号，Pages 部署有延迟，读数未变稍后重跑。
