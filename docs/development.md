# 开发手册

面向贡献者与维护者，用户侧安装与更新见 [README.md](../README.md)，发布操作见 [发布工作流](release-workflow.md)，构建见 [打包教程](packaging.md)。
代码风格、静态检查、回归用例与文案分别见 [代码规范](coding-style.md)、[规范扫描器](style-checker.md)、[测试](testing.md) 与 [写作规范](writing-style.md)，实测约束与踩坑见 [工程经验](lessons/README.md)。

## 环境搭建

1. 安装 `Python 3.11+`（勾选 Add to PATH）。
2. 克隆本仓库：`git clone <地址>`，装载根与接口包两棵不在版本库里，按 [挂载子仓](#挂载子仓) 自己 clone 进去。
3. 在项目根创建虚拟环境：`python -m venv .venv`，激活：`.venv\Scripts\activate`。
4. 安装依赖与开发工具：`uv sync --all-packages`，镜像源可自行配置。
5. 启动：`python -m bootstrap`，先弹"选择机器人"，选定或新建实例后出现管理面板。
6. 首次运行点"新建"，平台下拉只列本机装着适配器包的平台，装新的走下拉右侧"管理平台组件"，按提示填凭证即生成 `instances/<身份码>/`，启动后按配置向导填写。
7. 实例目录含 `config.toml`、`profile.json`（凭证、插件启用集与目录指纹）、`persona/`（`persona.md`、`template.sha256`、`applied.cache`）、`records/`、`db/`（`bot.db` 与 `backups/`）、`logs/`，整体不进版本库。
8. 凭证存 `profile.json`，不进配置面板，改凭证走选实例窗的编辑入口。
9. 身份码经环境变量 `FINSHINIMPACT_PROFILE` 传递，选窗在任何业务模块 import 前写入，发布包手动运行 `runtime\python.exe main.py` 也会先弹选择窗。
10. `config.toml` 住在实例目录，根目录那份不读取，老配置自己备份后重填 API Key 与人设。

## 新增插件（代码声明流程）

### 插件目录与基类

- 建目录 `src/bundled/<Name>/`，`__init__.py` 里写一只 `BasePlugin` 子类，一只模块只准有一只。
- 插件与适配器形状从 `finshin_sdk.domain` 取，处理上下文与平台能力从 `finshin_sdk` 顶层取。
- 这几只方法都可以不写，不写即没有那一类能力，交出的清单按交出的顺序生效。
- `message_routes` 交按顺序判定的路由，谓词只吃归一后的处理上下文，`background_loops` 交无参常驻协程，`queued_actions` 交可排队动作。
- 动作名写成 `插件名.动作`，前段不等于自己的插件名整只拒装，循环随 Bot 服务起停，异常日志等停服收拢时落，循环本身不重跑。
- `BasePlugin`、`MessageRoute`、`QueuedAction`、`MomentSubscription` 从 `finshin_sdk.domain` 取，`HandlerContext` 从 `finshin_sdk` 顶层取，共用守卫、谓词与话术放 `src/bundled/_shared/`。

### 平台机会

- `platform_moments` 交 `MomentSubscription(时机, 协程)`，同一时机按交出顺序跑，新增时机在 `PlatformMoment` 加一名，不在入口基类加方法。
- `BEFORE_ENGINE_RUN` 在轮询前跑，重活自己交线程池，`IDENTITY_CHANGED` 在主人或生效正文变了、清历史时跑，`CONFIG_VERIFIED` 在配置通过时跑，此刻内存里已是刚验过的值，盘上可能还是旧值。
- 协程都收同一份 `CapabilityCall`，要说话从它的 `say` 拿，异常由装载侧兜住并记插件名与时机名，平台接着跑。

### 插件声明

- 目录内放 `_declaration.py`，交一个 `PluginDeclaration`：

```python
from finshin_sdk.domain import CommandHelp, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="示例",
    summary="一句话说明",
    assets=(),
    help=(
        SectionHelp(
            section="示例",
            commands=(CommandHelp(cmd="demo", desc="示例命令"),),
        ),
    ),
)
```

- 文件顶层只许 `finshin_sdk` 导入、赋值与 `def`，默认值与装饰器同组检查，违规报「文件:行号」，读取时不执行插件包 `__init__.py`。
- 缺文件、`DECLARATION` 形状不合法或接口包区间不满足，整只插件不收。
- 恒启用与加载档位由本体随包表决定，表里没有的按常规档，外部插件一律常规档，注册序列与帮助图自动消费声明。
- 本插件独有顶层库写在同目录 `pyproject.toml` 的 `[project].dependencies` 里并 pin 版本。
- 外部插件 `[project].name` 必须写成 `finshin-plugin-<目录名>`，`dependencies` 必须写明 `finshin-sdk` 区间，缺声明、没写区间或本机不在区间即不加载，日志写明插件名、要求区间与本机版本。
- 随包插件取目录名，不查接口包区间，依赖写在项目根 `pyproject.toml`。
- 命令可见性由 `SectionHelp.commands` 决定，未写贡献的命令按未知命令拦截。

### 命令输入

- 可选输入写在 `CommandHelp.flags`，纯开关如 `FlagHelp(name="-i", desc="说明")`，`-h` 全命令默认可用。
- 带值开关写 `default`，例如 `FlagHelp(name="-t", desc="说明", default=0.0)`，命令没写即落默认值，只认整数、小数与非空文本，真假值、空文本或数组整只拒收，开关数量不设上限。
- 默认值类型即开关取值类型，整数拒小数，小数把 `5` 转成 `5.0`，文本原样交出，收不进即判多余输入，范围由命令自己判，判不过回一句要什么。
- 值取开关后紧接的一段，后跟别的开关即缺值，位置参数只认第一只开关前的片段，`args` 写命令后面要带的内容，写了即收开关之前的全部片段，没写一段都不收。
- 平台层只交出原顺序片段，多余输入在私聊与群里回用法，群里引用发起消息，频道静默，命令缺参的补救归命令侧。
- 分步输入的中止串取 `finshin_sdk.domain` 的 `StepInput.STOP`。

### 权限与提示

- 权限档写 `CommandHelp.role`，取 `CommandRole.OWNER` / `CommandRole.ADMIN` / `CommandRole.MEMBER`，不写即 `CommandRole.MEMBER`，装配时与 `require_role(CommandRole.X)` 比对，不符整份拒装。
- 对话门槛仍写进判定函数读 `role_of`，命令声明不认，帮助图按档位自动追加（仅主人）/（需授权），`SectionHelp.note` 只写字段表达不了的规矩。

### 装库链路

- 插件库按 `[project].dependencies` 收集，资源取 `PluginDeclaration.assets`，选定实例后启动前统一结算，pip 包与资源逐个实测，缺哪补哪。
- 装完才放行启动，失败的插件自动禁用并弹窗，实例未保存插件选择时仅随包插件运行。

### 装卸纪律

- 禁用只改启用集，不删已装库，删库只由选窗"环境维护"里的手动依赖同步执行。

## 外部插件

1. 建目录 `finshin/plugin/<Name>/`，声明同上，`[project].name` 写 `finshin-plugin-<Name>`，代码放插件目录或其 `src`，导入名是 `plugin.<Name>`。
2. 装载前扫描源码，引了本体整只拒装并写明第一处位置，同名随包插件优先，被顶掉的在加载记录末尾显示"重名"按钮，点开写明插件名被谁占用。
3. 命令名被拿走的整只不装载，显示"冲突"按钮，点开逐条写明哪条命令被哪只插件占用，随包插件优先，两只外部插件同时勾选同命令则整组不装载。
4. 勾选与取消当场重算，不用重启或再保存，路由整套装载，摘不掉单独一条命令。

## 从 dev4 及更早的写法改过来

1. 模块属性 `spec` 那套改在 `__init__.py` 里写一只 `BasePlugin` 子类，一只模块只准有一只。
2. 领域词表从 `core.domain` 搬进 `finshin_sdk.domain`，归一快照从 `core.dto` 搬进 `finshin_sdk.dto`，`HandlerContext` 与 `CapabilityCall` 从 `finshin_sdk` 顶层取。
3. `PluginRoute` → `MessageRoute`、`PluginPredicate` → `RouteMatcher`、`PluginBackground` → `BackgroundLoop`、`TaskHandler` → `QueuedAction`、`timings` → `platform_moments`，`PlatformTiming` → `PlatformMoment`、`PluginTiming` → `MomentSubscription`、`PluginTimingRun` → `MomentRun`，`PluginSpec` 删除。
4. 内置对话动作名由 `chat` 改成 `AI.chat`。
5. 接口包撤掉 `ContentDTO` 的 `file_token` 与 `origin_ref`、`AdapterFieldSpec.default`、`BoundCommand.value_of`、`PrincipalRepository.find_by_key`，用到哪改哪。
6. 适配器声明从 `adapter.toml` 搬进 `pyproject.toml`，旧 TOML 插件标题、说明、资源与帮助搬进 `_declaration.py`，依赖搬进同目录 `pyproject.toml`。
7. 外部插件名从同目录 `pyproject.toml` 的 `[project].name` 读取，必须写成 `finshin-plugin-<目录名>`，`dependencies` 写明 `finshin-sdk` 区间，缺行或本机不在区间即不加载。

## 新增平台适配器

### 命名与发现

- 本体只认适配器声明表，键就是平台码，装载、依赖保留与引擎预热都从它取，新增平台不改本体。
- 目录名用平台码：`finshin/adapter/<平台码>/`，与声明里的 `platform` 同值，分发名 `finshin-adapter-tg`，导入名把连字符换成下划线，两处都由子仓 `pyproject.toml` 派生。
- 仓名以 `Finshin` 起头接词根，适配器族是 `FinshinAdapter` 加平台码大写，平台标识与入口点段的键必须同值，判定只看声明值与字段形态。

### 在线目录

- 每行交平台码、分发名、版本、下载直链与指纹，适配器另带接口包要求，直链是独立整串。
- 行内那版是最新版，另嵌版本清单，每条交版本、下载直链与指纹，适配器另带接口包要求，最新版在前。
- 清单只收正式 release，一页取不完就翻页，全部列出，不设版本上限。
- 旧版的版本号取 wheel 文件名，没报指纹的旧版不进清单。
- 目录缺版本清单那段时按只有一版处理，老目录不必重发。
- 发布与刷新见 [子仓供件](release-workflow.md#子仓供件)，单独生成见 [在线目录](packaging.md#在线目录)。

### 仓与声明

- 每只适配器一只独立仓，clone 进 `finshin/adapter/<平台码>/`，主仓不记登记，声明在仓根 `pyproject.toml`，代码在 `src`，由 `package-dir` 映射。
- 入口由 `[project.entry-points."finshin.adapters"]` 交出，键写平台标识，值写 `入口模块:parts`，冒号后名字由本体规定。
- 装载侧认目录声明与已装适配器元数据两路，同平台两路都在时认目录，声明缺件、字段非法或入口不点名本平台即不进表。
- 引擎库与接口包要求写在 `[project].dependencies`，`[tool.finshin-adapter]` 只写 `platform`，目录生成只读这个值，平台自带库不在本体重复钉，同名同职责模块平铺，平台独有机制放 `features/`。

### 安装、更新与卸载

- 面板可联网装、更新与卸，失败按发行件点名，只装比本机新的版，也能从版本清单挑一版回退。
- 核过指纹的件记在本机，目录取不到时仍算可装，盘上那份不在目录、本机也没记指纹时不给装，版本串读不懂按不动处理。
- 卸一只只动那只包与只有它声明过的库，还有实例先用先拦，已装接口包进保留清单，源码仓挂着不给卸。

### 接口包要求

- 接口包要求形如 `finshin-sdk>=0.1.0,<0.2.0`，上下限都算数，没写即不设限。
- 本机不在区间内即拒在装载入口之前，面板装件前按同一要求拦，挡装的按钮置灰，"其他版本"窗写"不可安装"并置灰。

### 分层与运行时

- 分层与导入方向见 [分层职责](coding-style.md#分层职责)，安装见 [环境搭建](#环境搭建)，挂载见 [挂载子仓](#挂载子仓)，wheel 构建见 [子仓构建](packaging.md#子仓构建)。
- 入口模块交出平台显示名、配置段表、运行时装配、检查计划、引擎预热与凭证声明，运行时实例交出交互端口、插件路由挂载口与路由清单编译器，日志中间件由装载侧交来，插件按启用序列注册。

## 挂载子仓

开发只在克隆出来的的仓库里做，发布物没有工具配置、用例树与 `.git`。

- 挂载点：平台适配器 `finshin/adapter/<平台码>`，接口包 `finshin/sdk`，分发名与导入名由 `[project].name` 派生，连字符换下划线。
- 适配器仓 [`FinshinAdapterTG`](https://github.com/FinshinLabs/FinshinAdapterTG)，接口包仓 [`FinshinSDK`](https://github.com/FinshinLabs/FinshinSDK)。
- 适配器留空壳时装载侧跳过，接口包缺位时本体 import 失败。

1. 挂载：`git clone <子仓地址> <挂载点>`。
2. 日常改动在挂载点提交，推送跑 `git -C <挂载点> push origin main`，只推子仓自己那笔。
3. 改完跑 `.venv\Scripts\uv.exe sync --all-packages --reinstall-package <分发名>`，普通 sync 不重装子仓。
4. 面板与运行时读环境里那只包，不重跑这步，版本号与行为还是旧源码。
5. 更新跑 `git -C <挂载点> pull`，主仓 pull 不带动子仓，摘掉时连目录删除。
6. 主仓不记子仓提交号，版本对齐看各自声明的版本号。

## 新增规范扫描分节

1. 先在 [coding-style.md](coding-style.md) 写条文，写明判据与后果。
2. 在 `devtools/_style_checks/` 新建模块，只依赖 `_common`，单文件检查导出 `check(files)`，跨模块检查导出 `check(files, graph)`。
3. 在 `_common.py` 的 `SECTIONS` 加同名项，单文件检查进 `_registry.py` 的 `_FILE_CHECKS`，导入图检查在 `run_checks` 里单独调用。
4. 在 `devtools/tests/test_style_checker_meta.py` 的 `_SAMPLES` 补样本，要求见 [加用例的判据](testing.md#加用例的判据)。
5. 跑 `python devtools\check_coding_style.py devtools` 自查，再跑 `python -m pytest devtools/tests/test_style_checker_meta.py`。

## 更新方式

- **"版本变化"按钮**：点开先拉全部 release，用最新一版 tag 与本机版本比对，有新版先提示一句，再照常打开全版本清单，旧版本照样能翻，比对不当场更新，升级由启动器完成。
- **开发版**：手动拉取新代码（`git pull` 或下载源码覆盖），依赖有变动时重跑 [环境搭建](#环境搭建) 的 `uv sync --all-packages`。
- **打包版**：启动器每次拉起主程序前自动比对版本，弹窗确认后下载升级，用户配置、数据与日志一律保留。
  - 启动器本体随升级当场更换，换壳机制见 [升级换源码与启动器](packaging.md#升级换源码与启动器)。
  - 接口包版本由 `pyproject.toml` 的 `sdk-version` 钉住，升级程序才换到新版，启动器按本机记录核对，缺这一版或指纹不符时重取。
  - 各版本走自动升级还是手动整包，见 [旧版迁移](../README.md#旧版迁移)。
