# 开发手册

面向贡献者与维护者。其余文档各管一段：

- 用户侧安装与更新：根目录 [README.md](../README.md)
- 发布操作：[发布工作流](release-workflow.md)
- 构建与发布物：[打包教程](packaging.md)
- 代码风格：[代码规范](coding-style.md)，静态检查：[规范扫描器](style-checker.md)，回归用例：[测试](testing.md)，文案与指针：[写作规范](writing-style.md)
- 实测出来的约束与踩坑：[工程经验](lessons/README.md)

## 环境搭建

1. 安装 `Python 3.11+`（勾选 Add to PATH）。
2. 克隆本仓库：`git clone <地址>`。装载根与接口包两棵都不在版本库里，要按 [挂载子仓](#挂载子仓) 自己 clone 进去。
3. 在项目根目录创建虚拟环境：`python -m venv .venv`。
4. 激活虚拟环境：`.venv\Scripts\activate`。
5. 安装依赖与开发工具：`uv sync --all-packages`，镜像源可自行配置。
6. 启动：`python -m bootstrap`，先弹出"选择机器人"窗口，选定或新建实例后管理面板出现。
7. 首次运行在选择窗点"新建"，平台下拉只列本机装着适配器包的平台，装新的走下拉右侧"管理平台组件"。选平台后按提示填凭证，即生成实例文件夹 `instances/<身份码>/`。选中它点"启动"后按配置向导填写，填完即开始收发，无需手编文件。
8. 实例文件夹：
   - 内含 `config.toml`、`profile.json`（内有凭证与插件启用集、目录指纹）、`persona/`（内有 `persona.md`、`template.sha256`、`applied.cache`）、`records/`、`db/`（内有 `bot.db` 与 `backups/`）、`logs/`，整体不进版本库。
   - 凭证存 `profile.json`，不进配置面板，改凭证走选实例窗的编辑入口。
9. 身份码：
   - 经环境变量 `FINSHINIMPACT_PROFILE` 传递，单源定义在 `src/system/profile_env.py` 的 `_PROFILE_ENV`，选窗写入、业务模块导入期读取。
   - 身份码必须在任何业务模块 import 前确定。
   - 发布包解压后手动单跑 `runtime\python.exe main.py` 也会先弹选择窗，无需自行设置该变量。
10. `config.toml` 住在实例目录里，根目录那一份不读取，手头的老配置要自己备份，再重填 API Key 与人设。

## 新增插件（代码声明流程）

### 插件目录与基类

- 建目录 `src/bundled/<Name>/`，`__init__.py` 里写一只 `BasePlugin` 子类，一只模块里只准有一只。
- 插件与适配器形状从 `finshin_sdk.domain` 取，处理上下文与平台能力从 `finshin_sdk` 顶层取。
- 这几只方法都可以不写，不写即没有那一类能力，交出的清单按交出的顺序生效。
- `message_routes` 交按顺序判定的路由清单，谓词只吃归一后的处理上下文，装配时由平台侧编成引擎对象。
- `background_loops` 交常驻循环，元素为无参协程函数，随 Bot 服务起停：轮询开始即拉起，停服即取消。跑中途抛出即静默收摊，那行日志要等停服收拢时才落，循环本身不重跑。
- `queued_actions` 交可排队的动作，动作名写成 `插件名.动作`，前段不等于自己的插件名整只拒装。
- `BasePlugin`、`MessageRoute`、`QueuedAction`、`MomentSubscription` 从 `finshin_sdk.domain` 取，`HandlerContext` 从 `finshin_sdk` 顶层取。
- 要跨插件共用的守卫、谓词、话术放 `src/bundled/_shared/`。

### 平台机会

- `platform_moments` 交平台机会的订阅清单，元素写成 `MomentSubscription(时机, 协程)`，同一时机交多条即按交出的顺序跑。
- 平台机会列在下面，加新时机在 `PlatformMoment` 加一名，不在入口基类上加方法：
  - `BEFORE_ENGINE_RUN` 排在轮询开跑前，跑在服务线程的事件循环上，重活自己交线程池。
  - `IDENTITY_CHANGED` 排在主人或生效正文变了、清历史那一刻。
  - `CONFIG_VERIFIED` 排在配置校验通过那一刻，此刻内存里已是刚验过的值，盘上可能还是旧值。
- 轮到时协程都收同一份交代 `CapabilityCall`，要往外说话从它的 `say` 拿。
- 订阅的协程抛出的异常由装载侧兜住，落一行带插件名与时机名的日志，平台接着跑。

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

- 文件顶层只许 `finshin_sdk` 导入、赋值与 `def`，函数默认值与装饰器也按同一组限制检查，违规报「文件:行号」。
- 读取声明不执行插件包的 `__init__.py`，每次重新读取，不做缓存。
- 缺文件、`DECLARATION` 形状不合法或接口包区间不满足，整只插件不收。
- 恒启用与加载档位由本体 `src/system/plugin_roster.py` 定，表里没有的按常规档，外部插件一律常规档。
- 本插件独有的顶层库写在同目录 `pyproject.toml` 的 `[project].dependencies` 里并 pin 版本。
- 外部插件的 `[project].name` 必须写成 `finshin-plugin-<目录名>`，后缀与目录名完全一致，`dependencies` 必须写明 `finshin-sdk` 区间。
- 外部插件缺项目声明、没写接口包区间或本机版本不在区间内即不加载，日志写明插件名、要求区间与本机版本。
- 随包插件取目录名，不查接口包区间，库照旧写在项目根的 `pyproject.toml` 里。
- 注册序列与帮助图自动消费代码声明，随包表决定谁恒启用、谁排前面。
- 命令可见性由 `SectionHelp.commands` 决定，未写贡献的命令按未知命令拦截。

### 命令输入

- 命令的可选输入写在 `CommandHelp.flags`，help 侧取的就是这一份。
  - 纯开关写成 `FlagHelp(name="-i", desc="说明")`。`-h` 全命令默认可用、不必登记。
  - 带值开关写 `default`，例如 `FlagHelp(name="-t", desc="说明", default=0.0)`，命令没写这只开关即落默认值。
  - 默认值只认整数、小数、非空文本，写成真假值、空文本或数组整只拒收。
  - 默认值的类型即这只开关的取值类型：整数档拒收小数写法，小数档把 `5` 这类写法转成 `5.0`，文本档原样交出。
  - 收不进该档的写法判多余输入。范围仍由命令自己判，判不过回一句要什么。
  - 开关数量不设上限，值就是紧跟在开关后面的那一段，后面紧跟别的开关即判缺值。
  - 位置参数只认第一只开关之前的片段，开关之后出现裸段一律判多余输入。
  - `args` 写命令后面要带的内容，一句话说明，写了即收开关之前的全部片段，没写一段都不收。
  - 分段与绑定归 `finshin_sdk.domain` 的 `bind_command`，平台层只交出原顺序的片段。
  - 多余输入的表现为：私聊与群里给这条命令的用法，群里引用发起人那条消息，频道静默。
  - 命令自己缺参时的补救流程归命令侧实现。
- 命令要分步等下一条输入时，中止用的保留串取 `finshin_sdk.domain` 的 `StepInput.STOP`，别在插件里另写一份。

### 权限与提示

- 命令权限档写 `CommandHelp.role`，取 `CommandRole.OWNER` / `CommandRole.ADMIN` / `CommandRole.MEMBER`，不写即 `CommandRole.MEMBER`。
- 装配时与代码里 `require_role(CommandRole.X)` 的档位比对，对不上整份插件拒装。
- 对话场景的门槛仍写进判定函数读 `role_of`，命令声明不认。
- 帮助图的命令描述尾部按档位自动追加（仅主人）/（需授权），文案不要再手抄一份。
- `SectionHelp.note` 只写命令字段表达不了的规矩，比如私聊能不能用。

### 装库链路

- 插件的库按自家 `pyproject.toml` 的 `[project].dependencies` 收集，资源取 `PluginDeclaration.assets`，选定实例后在启动前统一结算。
- pip 包与资源都在启动前逐个实测，缺哪样补哪样。
- 装 wheel 时逐只点名重装，装完再按本机读到的版本复核一次。
- 装完才放行启动，装失败的插件自动禁用并弹窗告知。
- 实例未保存过插件选择时仅随包插件运行。

### 装卸纪律

- 禁用只改启用集，不删已装库。
- 删库只由依赖同步执行，入口是选窗"环境维护"手动菜单。

## 外部插件

1. 建目录 `finshin/plugin/<Name>/`，代码声明与字段同上，同目录 `pyproject.toml` 的 `[project].name` 写成 `finshin-plugin-<Name>`。代码放插件目录，也可放它的 `src` 子目录。
   - 导入范围见 [分层职责](coding-style.md#分层职责)。
   - 装载前扫描源码，引了本体的整只拒装，面板写明引用位置，一份多处只报第一处。
   - 两根目录一起扫，先读随包再读外部。外部插件的导入名是 `plugin.<Name>`，代码所在那一层按名字接到它，插件内部的相对引用走得通。
2. 与随包插件同名的那份不放行，改项目名或写进启用集都不认。
3. 被顶掉的那一份在面板单开一行，排在整张加载记录末尾，勾选位是"重名"按钮，点开写明插件名被谁占用。
4. 代码声明里的命令名已被拿走的整只不装载，面板把勾选位换成"冲突"按钮，点开逐条写明哪条命令被哪只插件占用。
   - 随包插件优先拿走命令名，同一命令名被两只外部插件一起勾上时整组不装载，状态文件怎么写都不算数。
   - 一只插件交出的是整套路由，摘不掉单独一条命令，命令名被抢走即整只不装载。
5. 勾选与取消当场重算，撞车的另一只立刻换成按钮，不用重启也不用再保存。

## 从 dev4 及更早的写法改过来

1. 入口写法：模块属性 `spec` 那套不再读取，改在 `__init__.py` 里写一只 `BasePlugin` 子类，一只模块只准有一只。
2. 导入行：领域词表从 `core.domain` 搬进 `finshin_sdk.domain`，归一数据快照从 `core.dto` 搬进 `finshin_sdk.dto`，`HandlerContext` 与 `CapabilityCall` 从 `finshin_sdk` 顶层取。
3. 交出的东西改名：`PluginRoute` → `MessageRoute`、`PluginPredicate` → `RouteMatcher`、`PluginBackground` → `BackgroundLoop`、`TaskHandler` → `QueuedAction`、`timings` → `platform_moments`。
   - 时机那几样一并归到 moment 词根：`PlatformTiming` → `PlatformMoment`、`PluginTiming` → `MomentSubscription`、`PluginTimingRun` → `MomentRun`。
   - `PluginSpec` 那只袋子删了。
4. 内置对话的动作名由 `chat` 改成 `AI.chat`，动作名归属见 [插件目录与基类](#插件目录与基类)。
5. 接口包撤掉没人用的形状：`ContentDTO` 的 `file_token` 与 `origin_ref`、`AdapterFieldSpec.default`、`BoundCommand.value_of`、`PrincipalRepository.find_by_key`。用到哪一处改哪一处，没用到不必动。
6. 把适配器声明从 `adapter.toml` 搬进 `pyproject.toml`，字段写法见 [仓与声明](#仓与声明)。
7. 旧 TOML 插件声明里的标题、说明、资源与帮助搬进同目录 `_declaration.py`，依赖搬进同目录 `pyproject.toml` 的 `[project].dependencies`。
8. 外部插件的名字从同目录 `pyproject.toml` 的 `[project].name` 读取，必须写成 `finshin-plugin-<目录名>`。`dependencies` 还须写明 `finshin-sdk` 区间，缺行或本机版本不在区间内即不加载。

## 新增平台适配器

### 命名与发现

- 本体只问 `load_adapter_manifests()` 那张表：键就是平台码，装载、依赖保留与引擎预热都从它取，新增平台不改本体，也不认路径或写死平台名。
- 装载根下的目录名用平台码，`finshin/adapter/<平台码>/`，与声明里的 `platform` 同值。
- 分发名 `finshin-adapter-tg`，可导入的包名是同一串把连字符换成下划线，两处都由子仓根的 `pyproject.toml` 派生。
- 仓名以 `Finshin` 起头接词根，适配器族是 `FinshinAdapter` 加平台码大写。
- 声明里的平台标识与入口点段的键必须同值，装载侧读到不一致就整份不进表。
- 判定只看声明里写明的值与字段形态，仓名与附件名都不参与。

### 在线目录

- 发出去的平台靠一份远端目录在场：每行交平台码、分发名、版本、下载直链与指纹五样，适配器另带接口包要求，直链是独立整串。
- 行内那一版是最新版，行里另嵌一段版本清单：每条交版本、下载直链与指纹三样，适配器另带接口包要求，最新一版排在最前。
- 清单只收正式 release，一页取不完就翻页接着取，全部列出，不设版本上限。
- 旧版的版本号取 wheel 文件名，没报指纹的旧版不进清单。
- 目录缺版本清单那段时按只有一版处理，老目录不必重发。
- 在线目录的发布与刷新见 [子仓供件](release-workflow.md#子仓供件)，单独生成见 [在线目录](packaging.md#在线目录)。

### 仓与声明

- 每只平台适配器一只独立仓，clone 进 `finshin/adapter/<平台码>/`，主仓不记这笔登记。
- 声明在仓根 `pyproject.toml`，代码在 `src` 那一层，由 `package-dir` 映射成包，包名取 `[project].name`。
- 入口由 `[project.entry-points."finshin.adapters"]` 交出，键写平台标识，值写 `入口模块:parts`，冒号后那个名字由本体规定。包目录改名要同步改这条值。
- 装载侧认两路声明：目录里那份与装进环境的适配器元数据，同一平台两路都在时认目录那份。声明缺件、字段非法或入口点不点名本平台即不进表，取不到包按拒载那句交代。
- 引擎库与接口包要求都写在 `[project].dependencies`，适配器的 `[tool.finshin-adapter]` 只写平台标识 `platform`，在线目录生成只读这个值。平台自带库不在本体重复钉。
- 同名同职责的模块平铺在包里，平台独有的机制放 `features/`。开发说明见那只仓的 README，源码开发见 [挂载子仓](#挂载子仓)。

### 安装、更新与卸载

- 面板可联网装、更新与卸。一条 uv 命令带全部 wheel 与 `--find-links`，接口包与适配器互相喂依赖，失败按发行件逐只点名。
- 只装比本机新的版，也能从版本清单挑一版回退。
- 核过指纹的件记进同目录 `downloaded.json`，目录取不到时本机记过的仍算可装。盘上那份既不在目录、本机也没记过指纹时不给装，版本串读不懂按不动处理。
- 卸一只只动那只包与只有它声明过的库，这一平台还有实例先拦。已装接口包进保留清单，卸掉最后一只适配器再同步也不删。
- 源码仓挂着时不给卸。
- 子仓版本号与 release 附件见 [子仓供件](release-workflow.md#子仓供件)。

### 接口包要求

- 接口包要求形如 `finshin-sdk>=0.1.0,<0.2.0`，上下限都算数，没写即不设限。
- 本机不在区间内即拒在装载入口之前，面板装件前按同一要求拦，挡装的那版按钮置灰，"其他版本"窗写"不可安装"并置灰。

### 分层与运行时

- 分层与导入方向见 [分层职责](coding-style.md#分层职责)。
- 接口包安装见 [环境搭建](#环境搭建)，源码挂载见 [挂载子仓](#挂载子仓)，wheel 构建与随包安装见 [子仓构建](packaging.md#子仓构建)。
- 入口模块交出运行时装配、频道探测与引擎预热，运行时实例交出交互端口、插件路由挂载口与路由清单编译器。
- 日志中间件实例由装载侧交来，挂上更新链那一步由各平台自己认，按启用序列注册插件全归装载侧。

## 挂载子仓

开发只在克隆出来的仓库里做。发布物是给用户用的绿色目录，里面没有工具配置、没有用例树、也没有 `.git`，拿它当开发环境只会发现形状缺一片。

- 挂载点有两处：平台适配器是 `finshin/adapter/<平台码>`，接口包是 `finshin/sdk`。
- 分发名与导入名由各自声明的 `[project].name` 派生，连字符换下划线。
- 适配器仓 [`FinshinAdapterTG`](https://github.com/FinshinLabs/FinshinAdapterTG)，接口包仓 [`FinshinSDK`](https://github.com/FinshinLabs/FinshinSDK)。
- 适配器那棵留下空壳目录时，装载侧读不到声明会跳过。
- 接口包那棵缺位时，本体 import 失败。

1. 挂载：`git clone <子仓地址> <挂载点>`。
2. 日常改动：在挂载点目录里改、提交，推送跑 `git -C <挂载点> push origin main`，只推子仓自己那一笔，主仓这边没有要提的东西。
3. 改完生效：跑 `.venv\Scripts\uv.exe sync --all-packages --reinstall-package <分发名>`，普通 sync 不重装子仓那棵。
4. 面板与运行时读的都是环境里那只包：不重跑这一步，屏上的版本号和行为都还是旧源码的。
5. 更新：`git -C <挂载点> pull`。主仓 pull 不带动子仓，两边各拉各的。
6. 摘掉：连目录一并删掉 `<挂载点>`。
7. 主仓不记子仓停在哪个提交号。要把两边版本对上，看各自声明里的版本号。

## 新增规范扫描分节

1. 先在 [coding-style.md](coding-style.md) 写条文，写明判据与后果。
2. 在 `devtools/_style_checks/` 新建模块，只依赖 `_common`。
   - 单文件检查导出 `check(files)`。
   - 跨模块消费者检查导出 `check(files, graph)`。
3. 在 `_common.py` 的 `SECTIONS` 加同名一项，分节名写法见 [分节登记](style-checker.md#分节登记)。
   - 单文件检查进 `_registry.py` 的 `_FILE_CHECKS`。
   - 导入图检查在 `run_checks` 里单独调用并传入导入图。
4. 在 `devtools/tests/test_style_checker_meta.py` 的 `_SAMPLES` 补样本，要求见 [加用例的判据](testing.md#加用例的判据)。
5. 跑 `python devtools\check_coding_style.py devtools` 自查。
6. 跑 `python -m pytest devtools/tests/test_style_checker_meta.py`。

## 更新方式

- **"版本变化"按钮**：点开先拉全部 release，用最新一版的 tag 与本机版本比对，有新版先提示一句，再照常打开全版本清单，旧版本照样能翻。比对不当场更新，升级由启动器完成。
- **开发版**：手动拉取新代码（`git pull` 或下载源码覆盖），依赖有变动时重跑 [环境搭建](#环境搭建) 的 `uv sync --all-packages`。
- **打包版**：启动器每次拉起主程序前自动比对版本，弹窗确认后完成下载升级，用户配置、数据与日志一律保留。
  - 启动器本体随升级当场更换，换壳机制见 [升级换源码与启动器](packaging.md#升级换源码与启动器)。
  - 接口包版本由 `pyproject.toml` 的 `sdk-version` 钉住，升级程序才换到新版，启动器按本机记录核对，缺这一版或指纹不符时重取。
  - 各版本走自动升级还是手动整包，见 [旧版迁移](../README.md#旧版迁移)。
