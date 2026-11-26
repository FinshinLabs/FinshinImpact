# 打包教程

所有命令在项目根目录的 PowerShell 中执行，环境搭建见 [环境搭建](development.md#环境搭建)，发布顺序见 [发布工作流](release-workflow.md#总流程发布日按序执行)。

## 原理

发布物指构建出来的绿色便携目录，发布包指分发它的那只 zip 文件。

```text
FinshinImpact\
├── FinshinImpact.exe   启动器（用户双击这个）
├── _internal\          启动器运行库
├── main.py             程序入口，走引导层
├── runtime\            嵌入式 Python 原料，首启自装于此
└── src\                代码文件
```

- 首启按指定版本取接口包并核指纹，准备运行环境、迁移旧配置后拉起主程序，插件依赖与浏览器内核由引导层在启动前按需安装，不在首装链路。
- 旧配置迁移按形状判定，写回前留 `config.toml.bak`（已有则不覆盖），单份失败只跳过。

### 升级换源码与启动器

- 启动器按版本与指纹补装接口包，成功清临时件，失败保留供续装，升级时同指纹跳过。
- 启动器随升级换壳，新壳慢时旧壳兜底，接管失败下次重试，运行环境保留在原目录。
- 更新入口与触发方式见 [更新方式](development.md#更新方式)。

### 按名字找的文件

- `runtime\python-embed.zip` **改名会坏**，`payload\uv.zip` 供首启解出 `uv.exe`，取用后 payload 自动删除。

### 依赖清单

- 要装的库出自 `pyproject.toml` 的核心依赖，`runtime\.installed` 记清单摘要，清单没变下次跳过安装。
- 启动器装依赖只追加，删库入口见 [装卸纪律](development.md#装卸纪律)，下载缓存放 `runtime\uv-cache`，装完不删，手动清理走选窗"环境维护"里的"清理下载缓存"。

## 构建

### 构建命令

版本定稿与构建次数见 [构建 zip](release-workflow.md#构建-zip)，zip 名取自 `pyproject.toml`。

```powershell
python -m PyInstaller --version
python packaging\build.py
```
成功标志：末行打印 `完成：dist\FinshinImpact-vX.Y.Z.zip`。

### 构建步骤

- 编译启动器，白名单组装并排除 `*.egg-info` 等开发残留，只在临时副本里构建，或仓内构建后清 `build\`、`*.egg-info`、`dist\`，包内 `pyproject.toml` 与仓里那份一字一样。
- 下载嵌入式 `Python` 与 `uv`，只走镜像，zip 逐条目校验，`uv` 另比对官方 sha256，不过会中止，加速镜像名单只在 `github-mirrors` 键里维护。
- 用随包嵌入式解释器预编暂存区 `src` 与 `main.py` 的字节码，按内容判断是否复用，用户解压即热，首启不必现场编译。

### 参数

- `--no-launcher`：跳过编译环节。
- `--check`：逐行打印本地版本号、远端 tag、本地 zip（大小与 sha256 前缀）、在线版本页、发布包 gh-proxy 与 ghproxy.net 的镜像，远端资产大小与本地包一致才算上传闭环，推 tag 前报"tag 缺失"、发布前报"不可达"属正常。

## 子仓构建

- 子仓挂载见 [挂载子仓](development.md#挂载子仓)，版本号与附件要求见 [子仓供件](release-workflow.md#子仓供件)。

```powershell
# 平台适配器
uv build finshin/adapter/<平台码> --wheel

# 接口包
uv build finshin/sdk --wheel
```

- 适配器产物名形如 `finshin_adapter_tg-<版本>-py3-none-any.whl`，构建只核 `pyproject.toml` 钉死的接口包版本能走镜像从 GitHub release 取到且指纹一致，不把 wheel 打进发布包。

## 在线目录

```powershell
python packaging/gen_catalog.py <输出路径>
```
- 账号取自 `GITHUB_REPOSITORY`，发布与刷新时机见 [子仓供件](release-workflow.md#子仓供件)。

## 构建缓存

- **启动器指纹复用**：编译前比对 `launcher.py` 源码与 `assets\app.ico` 的合并哈希，未变即跳过 PyInstaller 复用旧包，**原料缓存**放 `dist\_cache`，清缓存就删该目录，缓存名带版本号，升级 `_EMBED_VERSION` 或 `_UV_VERSION` 后失效。

## 本地测试

拿构建出的 zip 走一遍用户路径：

1. 把 zip 复制到别处解压，不在 `dist\` 里测试。
2. 双击 `FinshinImpact.exe`，等待环境安装完成。
3. 验证首装：
   - 按 [环境搭建](development.md#环境搭建) 创建实例，完成向导后验证收发消息。
   - 再开一次，确认走的是跳过安装那条路径，判据见 [依赖清单](#依赖清单)，并确认 `payload\` 的清理结果，见 [按名字找的文件](#按名字找的文件)。
4. 升级路径按 [旧版迁移](../README.md#旧版迁移) 验证。
5. 测完删掉测试目录。

## 报毒

构建使用 `--onedir`，不启用 UPX，不写注册表，zip 可传 VirusTotal 检查，出现具体家族名时先停发。

## 排查

| 现象 | 处置 |
| :--- | :--- |
| 进度窗红色报错 | 无需处理，程序自动换源/回退重试，有"已自动换源"即正常 |
| 环境安装失败 | 三源全部失败才会弹。看进度窗尾部输出，恢复网络重双击即可续装 |
| 升级失败 | 进度窗打印失败原因并按当前版本启动。镜像全部失败才会触发，稍后重试即可 |
| 内嵌运行环境包损坏 | zip 被截断，重下重传 |
| 双击无反应 | SmartScreen 拦截：右键属性解除锁定，或"更多信息 → 仍要运行" |
| 升级后版本没变 | 查 Release 资产是否传对 tag，再 `--check` 版本页读数 |
