# 🐳 Finshin Impact

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://docs.python.org/3.11/)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Changelog](https://img.shields.io/badge/changelog-CHANGELOG.md-blue.svg)](CHANGELOG.md)

> 基于 `Python` 的异步机器人，平台由适配器接入，带 `PySide6` 桌面管理面板。
>
> 当前可用平台：Telegram。
>
> *鱼神，启动！*
>
> **仅限 `Windows` 用户使用。**

升级前先看 [旧版迁移](#旧版迁移)，破坏性变更和要手动处理的文件都在那一节。

## 🚀 快速开始<a id="快速开始"></a>

1. **下载**：取最新的 `FinshinImpact-vX.Y.Z.zip`。[国内镜像 1](https://gh-proxy.com/https://github.com/FinshinLabs/FinshinImpact/releases) ｜ [国内镜像 2](https://ghproxy.net/https://github.com/FinshinLabs/FinshinImpact/releases)。
2. **解压**：任意可写目录，如 `D:\FinshinImpact`。
3. **首启**：双击 `FinshinImpact\FinshinImpact.exe`，自动取接口包并装好运行环境，期间保持联网。
4. **新建实例**：点"新建"，下拉"平台"菜单选择，根据提示填写平台所需配置。没装过平台的先点"管理平台组件"，按需安装。
5. **管理插件**：选中一个实例，点"插件设置"。
6. **启动实例**：选中一个实例，点"启动"，启动后按配置向导填写必要内容，即可开始使用。

**注意**：升级会整树替换 `src\` 与 `assets\`，根目录下同名的 `main.py`、`pyproject.toml` 也会覆盖。`instances\`、自动装好的运行环境与自己建的文件不动。

## 📑 目录<a id="目录"></a>

[🚀 快速开始](#快速开始) ｜ [✨ 功能特点](#功能特点) ｜ [🛠️ 技术栈](#技术栈) ｜ [📖 开发与维护](#开发与维护) ｜ [⬆️ 旧版迁移](#旧版迁移) ｜ [❗️ 温馨提示](#温馨提示) ｜ [📄 许可证](#许可证)

## ✨ 功能特点<a id="功能特点"></a>

- **免安装分发**：解压双击即用，首启按程序内置的版本联网取接口包，运行环境与依赖自动装好，内置版本检测更新与配置校验。
- **桌面管理面板**：窗口里实时看日志，配置、平台连接、AI 接口、插件启用与网络诊断都在面板里改。
- **平台组件**：在"环境维护"里点"管理平台组件"，在线装、更新平台适配器，可换其他版本，与本机接口包不兼容的那一版不给装。还有实例在用的平台不给卸。
- **多实例隔离**：每个机器人独占一个实例目录，配置、人设、库、记录、日志互不干扰。拦截同一身份码的实例重复启动。
- **权限管理**：分为主人、管理员、成员三档，授予和撤销全局生效，可用功能按权限分。
- **插件化**：随包插件必选，三方插件放进安装目录 `finshin\plugin\`，面板勾选启用，未启用即不响应，依赖自动安装，配置随面板管理。插件标题、说明、资源与帮助写在同目录 `_declaration.py`，外部插件名、依赖与接口包区间写在 `pyproject.toml`。

## 🛠️ 技术栈<a id="技术栈"></a>
| 组件 | 版本/描述 |
| :--- | :--- |
| **语言** | [`Python 3.11+`](https://docs.python.org/3.11/)，全链路 `asyncio` |
| **桌面面板** | [`PySide6`](https://www.qt.io/qt-for-python)（管理面板与仪表盘日志） |
| **存储** | [`SQLite`](https://www.sqlite.org/)（按实例分库，WAL 模式） |
| **接口包** | 本体与插件、适配器共用的形状，独立仓 [`FinshinSDK`](https://github.com/FinshinLabs/FinshinSDK) |
| **平台连接** | Telegram：[`FinshinAdapterTG`](https://github.com/FinshinLabs/FinshinAdapterTG)，基于 [`aiogram 3.x`](https://docs.aiogram.dev/) 长轮询 |

## 📖 开发与维护<a id="开发与维护"></a>

- 🤖 **开发前先看**：[代码规范](docs/coding-style.md) 与 [开发手册](docs/development.md)，交给 AI 编码工具时把这两份喂给它，改完按规范自查。
- 🧭 **仓库导航**：[写作规范](docs/writing-style.md)、[规范扫描器](docs/style-checker.md)、[测试](docs/testing.md)、[发布工作流](docs/release-workflow.md)、[打包教程](docs/packaging.md)、[`.gitmessage`](.gitmessage)、[工程经验](docs/lessons/README.md)。
- 🧩 **插件写法**：见 [开发手册的插件声明](docs/development.md#插件声明)，配置字段表单源在接口包 [`FinshinSDK`](https://github.com/FinshinLabs/FinshinSDK)。

## ⬆️ 旧版迁移<a id="旧版迁移"></a>

旧写法的配置段与 `plugins.toml` 的插件状态在启动时自动搬进新位置，搬之前留 `.bak`。下面只列要手动处理的事。

### v1.0.0-alpha.7.dev9

- 接口包首启自动换到 0.3.0。到"环境维护"里的"管理平台组件"把 Telegram 适配器更新到 0.3.0，0.2.x 与这一版的接口件不兼容。
- 自己写过外部插件的人才要动：同目录 `plugin.toml` 不再读取，标题、说明、资源与帮助搬进 `_declaration.py`，名字、依赖与 `finshin-sdk` 区间写进 `pyproject.toml`。逐项改法见 [从 dev4 及更早的写法改过来](docs/development.md#从-dev4-及更早的写法改过来)。

### v1.0.0-alpha.7.dev8 及更早

- dev6：仓库搬到组织 `FinshinLabs`，旧包里的版本页地址已取不到：手动下新包覆盖解压即可，配置、记录、库与日志都在 `instances\`，不受影响。
- dev5：解压件不再自带平台适配器，首次建实例要先在平台下拉右侧"管理平台组件"里在线装一只，装的过程保持联网。已有实例的配置、记录与库都不动。
- dev4：自己写过插件或适配器的人才要动：入口写法、取用来源和动作名都换了。
- dev1 与 dev2：没改动过人设正文的实例自动跟新版模板，升级后第一条消息清空上下文与 `records\` 记录，要留存先自行备份。

### v1.0.0-alpha.6 及更早

- 实例目录分隔符统一成点号，`instances\tg-<id>` 要改成 `instances\tg.<id>`，不改名列不出该实例。
- 库进 `db\`、记录进 `records\`、帮助图进 `help\`，程序不动也不删旧 `data\`。要留记录就把 `data\ai_records\` 的 `.md` 挪进 `records\`，之后自行删掉 `data\`。
- 记录改按窗口存，一群一份、一私聊一份。按人分的旧文件不再读写，要留自行合并。授权名单改按用户在本平台的 id 记，上一版存的名单不再命中，主人要重新 `/grant` 一遍。
- 人设文件搬进 `persona\`，根目录旧的 `persona.md` 与 `.persona.base` 不再被读取，自定义正文要自己挪成 `persona\persona.md`。面板撤掉"超时（秒）"与"全局设置"整页，`config.toml` 里留下的 `[global]` 段不再被读取，下次保存配置即写掉。

### v1.0.0-alpha.4 及更早

- 自动升级过来首次启动会刷一段 `uv pip uninstall` 报错并弹"依赖安装失败"，属旧启动器拿着作废的清理清单空跑，再双击一次即正常。
- 更早的旧装机连不上自动升级链，只能手动整包：先备份根目录 `config.toml` 与 `instances\`，删旧目录再解压新包，缺的配置按 [快速开始](#快速开始) 里的"建实例"重填一遍。

[⤴️ 返回目录](#目录)

---

## ❗️ 温馨提示<a id="温馨提示"></a>

仍在测试阶段，遇到报错请连同 `instances\<身份码>\logs\` 一起反馈。

- **接口包**：取不到时启动窗口会写明原因，退出重开即续装。
- **代理**：Telegram 适配器的连接设置里，代理默认自动模式，填了地址优先用它，不通会自动尝试系统代理与直连。可强制仅配置代理、仅系统代理或仅直连，全不通时报错里给出可用的本机端口。

## 📄 许可证<a id="许可证"></a>

MIT，详见 [`LICENSE`](LICENSE)。

Made by **lym2006**
