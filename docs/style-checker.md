# 规范扫描器

扫描器在 `devtools/check_coding_style.py`，按 [代码规范](coding-style.md) 与 [写作规范](writing-style.md) 的分节静态检查代码与入库 md，只报不改，输出供人工核实。

## 跑法

```powershell
# 默认扫 src，按分节输出违规清单
python devtools\check_coding_style.py

# 只扫指定目录或文件
python devtools\check_coding_style.py src\bot

# 只看规则明确可判的硬性违规
python devtools\check_coding_style.py --hard-only

# 只看某一节，可重复
python devtools\check_coding_style.py --section 注释
```

- 命令行给了路径就只扫那几个，没给即默认扫 `src`，子仓 py 文件按挂载现场点名进扫描，闸门命令自动带上，手动跑把目录写上。
- 入库 md 恒随装载，不受命令行路径影响，名单是根 `README.md` 与 `CHANGELOG.md`，加 `docs/` 与 `assets/` 下的 md，`docs/design/` 除外。
- `CHANGELOG.md` 只进「日志与文案」，其余 md 只进「文档写法」，细则只吃对口载体。
- `[H]` 是硬性，须改，`[?]` 是待核，人工判断后再改，待核条数与上一轮比对，只许减不许增，基线取登记完豁免清单后的读数。
- 提交与发布的扫描范围、通过标准见 [五项闸门](release-workflow.md#五项闸门提交与发布前跑齐)，子仓范围见 [子仓供件](release-workflow.md#子仓供件)，没挂载的子仓没得扫。
- 措辞类静态查不出，背景解释与变更叙述见 [只写现状](coding-style.md#只写现状)，禁词兜底见 [措辞](coding-style.md#措辞)。

## 待核豁免清单

审过并决定不改的待核登记在 `devtools/style_waivers.toml`，随仓库走，扫到同一条即静音，末尾补一行"已豁免 N 条"。

- 一条由 `section`、`path`、`reason` 组成，可选 `match` 收口到消息里的关键字，匹配只看分节、文件与消息子串，不写行号。

### 豁免范围

- 只罩待核，单文件行数超限不罩，只拆分或调整扫描阈值。

- 只登记裁定永久不改的，加条目前先问是哪个判据太宽，能收紧判据就别拿豁免兜底。
- 条目不再命中即转一条硬性"失效豁免"报出，本轮没装载的路径、只扫单个分节都不作数，只扫本体时指向子仓的条目不算失效。
- `--hard-only` 只裁输出，豁免命中与失效一律按全量待核算。

## 分节与检查文件

- 一个分节一个主模块，摆在 `devtools/_style_checks/`。

- [文件骨架（自上而下）](coding-style.md#文件骨架自上而下)：`_s1_skeleton.py`
- [拆分粒度](coding-style.md#拆分粒度)：`_s2_split.py`
- [Docstring](coding-style.md#docstring)：`_s3_docstring.py`
- [注释](coding-style.md#注释)：`_s4_comment.py`
- [命名与门面导出](coding-style.md#命名与门面导出)：`_s5_naming.py`、`_s5b_naming_style.py`、`_s5c_constants.py`、`_s5d_access.py`、`_s5f_facade_exports.py`
- [魔法数字与字符串](coding-style.md#魔法数字与字符串)：`_s6_magic.py`、`_s6b_protocol_strings.py`、`_s6c_link_home.py`
- [枚举](coding-style.md#枚举)：`_s5e_enum.py`
- [日志与文案](coding-style.md#日志与文案)：`_s7_text.py`、`_s7b_changelog.py`
- [文案类（skin/messages/）](coding-style.md#文案类skinmessages)：`_s8_messages.py`
- [回调形参](coding-style.md#回调形参)：`_s8b_callback_param.py`
- [类型注解](coding-style.md#类型注解)：`_s9_typing.py`
- [导入](coding-style.md#导入)：`_s10_import_direction.py`
- [文档写法](coding-style.md#文档写法)：`_s11_docs.py`
- [按钮样式](coding-style.md#按钮样式)：`_s12_buttons.py`

- 地址的家的清单按路径片段匹配，家外裸写按硬性报，分层职责不由本扫描器检查，判据见 [分层职责](coding-style.md#分层职责)，命令见 [五项闸门](release-workflow.md#五项闸门提交与发布前跑齐)。

## 工具树直连内部实现

允许范围见 [对外判据](coding-style.md#对外判据)。

- 私有模块访问检查由 `_s5d_access` 执行。
- 消费者范围检查由 `_s5_naming` 执行。

## 符号私有性查哪些名字

"对外"判据见 [对外判据](coding-style.md#对外判据)。

- 模块级的函数、类与别名赋值都进检查，别名按名字样式分档，全大写与小写蛇形归 `_s5c_constants`，大写开头驼峰归 `_s5_naming`，右侧是 `TypeVar`／`NewType`／`ParamSpec`／`TypeAliasType` 调用的不判。
- 标识类型集中定义处按设计公开。
- 模块级小写蛇形赋值走 `_s5c_constants` 的另一条判据，加 `_` 前缀或收进命名空间类，不看消费者。

## 门面出口查什么

判据见 [门面导出](coding-style.md#门面导出)。

- 私有模块的模块级 `from` 导入表与消费方取用名求交集，命中报硬性，消费方应改从来源模块直连（`_s5_naming`）。
- 惰性门面的 `_SYMBOL_MODULES` 指向公开模块报硬性，消费方应直连该模块（`_s5f_facade_exports`）。
- 包外经门面取用同包公开子模块代发的符号报硬性，消费方应直连该子模块（`_s5f_facade_exports`）。
- 门面声明 `__all__` 报硬性，导入即出口（`_s5f_facade_exports`）。

## 回调形参查什么

- 协程形参含 `Message` 注解或 `platform_raw` 时进入回调检查，否则跳过，事件与上下文形参的命名、位置、注解违规报硬性。
- 类名以 `Middleware` 结尾时检查 `__call__`，形参与关键字隔断违规报硬性。
- 同步函数与协程都检查相邻必填、可选参数是否同型，命中时报待核，形参写法见 [回调形参](coding-style.md#回调形参)。

## 分节登记

- 分节名在各检查模块里写死字面量，不按 `SECTIONS` 的位置取，模块写了 `SECTIONS` 里没有的名字，排序时当场报错。
- 检查模块未接入 `_registry.py` 时不会执行，新增步骤见 [新增规范扫描分节](development.md#新增规范扫描分节)。

## 测试目录豁免

名为 `tests` 的目录整体跳过，点名扫它也 0 条，其余用例放宽项见 [用例放宽的部分](testing.md#用例放宽的部分)。
