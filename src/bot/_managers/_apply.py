"""配置应用

- 校验当前配置并决定是否重启引擎
- 按类保存单个来源的校验与写盘
"""

from typing import TYPE_CHECKING

from exceptions import ConfigOutputError
from finshin_sdk.domain import PlatformMoment
from skin.messages import CheckMessage, DialogMessage
from system.profile_env import get_profile, read_token
from ui import gui_bridge
from utils import config_manager
from utils.config import (
    FieldErrors,
    ProbeRecord,
    SourceSaveRequest,
    load_config,
    merge_source_config,
    owner_item,
    save_config,
)
from utils.init_files import save_persona_text
from utils.network import link_report
from utils.paths import PLATFORM
from utils.persona import applied_persona_text, load_persona_cache, save_applied_persona

from .._adapter_host import parts_for
from ..error_guard import error_guard

if TYPE_CHECKING:
    from ._manager import BotManager


def get_token_func() -> str:
    """读取校验用的凭证"""
    return read_token(get_profile())


def _is_token_fatal(errors: FieldErrors) -> bool:
    """判定是否凭证致命错

    - 面板改不了凭证，报错即致命
    """
    return parts_for(PLATFORM).credential.item in errors


class ConfigApplier:
    """配置应用器"""

    def __init__(self, host: "BotManager") -> None:
        self._host = host

        # 最近一次生效并重启过引擎的参数指纹：一致则跳过重启防闪断
        self._last_applied: tuple[str, str | None] | None = None

        # 三级解析出的生效通道，引擎与指纹均以此为准
        self._resolved_proxy: str | None = None

        # 上次生效的对话身份：(主人 id, 生效正文)，任一项变化即清历史
        self._last_identity: tuple[str, str] | None = None

    @error_guard("配置校验")
    async def apply_config(
        self,
        probes: dict[str, ProbeRecord] | None = None,
        *,
        force_restart: bool = False,
    ) -> None:
        """应用当前配置

        - 校验通过才重启服务
        - 没过即请用户重填配置
        - 向导交来的检测记录与盘上指纹一致时直接复用
        """
        host = self._host
        if host._shutdown:
            return

        # 重验期间先收回就绪，阻止 EDIT 弹窗读到半新半旧的配置
        gui_bridge.config_ready_changed.emit(False)

        await host._settings_manager.execute()
        verified = await host._settings_manager.verify_connectivity(probes=probes)
        if not verified:
            await self._settle_failure(False)
            return

        # 生效通道接引擎：配置不通时自动落到系统代理/直连
        self._resolved_proxy = host._settings_manager.resolved_proxy

        await self._reset_stale_identity()
        await self._restart_verified(force=force_restart)

    async def _restart_verified(self, *, force: bool = False) -> None:
        """重启已通过校验的服务"""
        host = self._host
        try:
            fingerprint = self.get_config_func()
        except Exception:  # 参数不可得：不做跳过优化，照常重启
            fingerprint = None
        if not force and fingerprint is not None and self._last_applied == fingerprint:
            # 生效通道与引擎参数未变：验证通过即保持引擎运行，不闪断重启
            host._logger.info("配置验证通过，运行参数未变，跳过重启")
            await self._announce_config_ready()
            return

        # 只有换掉在跑的服务才叫重启：首次起服务由启动日志说话，不弹重启窗
        hot_restart = self._last_applied is not None
        if hot_restart:
            gui_bridge.service_restarting.emit(True)
        try:
            host.stop_service()
            await host._service_manager.execute()
            self._last_applied = fingerprint
            host._logger.info("配置验证通过，服务运行中")
        except Exception:
            if hot_restart:
                # 重启半路报错：收掉等待窗，结论交护栏那条路说
                gui_bridge.service_restarting.emit(False)
            raise

        # 配置已加载且引擎已就位，最后广播：结果由界面写进重启那只窗
        await self._announce_config_ready()

    @error_guard("单类配置校验")
    async def apply_source(self, request: SourceSaveRequest) -> None:
        """校验并保存单个来源

        - 表外异常也回一句失败，面板不留在忙碌态
        """
        host = self._host
        try:
            if host._shutdown:
                return
            group = request.group
            config_manager.load(request.candidate)
            passed = await host._settings_manager.verify_connectivity(
                group=group, probes=request.probes
            )
            if not passed:
                host._logger.error(f"来源 {group} 未准备好，配置未写入")
                await self._settle_failure(True)
                gui_bridge.config_source_done.emit(
                    group, False, dict(host._settings_manager.last_errors), None
                )
                return

            if request.write:
                candidate = merge_source_config(
                    config_manager.schema, load_config(), group, request.candidate
                )
                try:
                    save_config(candidate)
                except ConfigOutputError as e:
                    host._logger.error(CheckMessage.WRITE_FAILED.format(err=e))
                    await host._settings_manager.execute()
                    gui_bridge.config_ready_changed.emit(False)
                    self._request_setup()
                    gui_bridge.config_source_done.emit(
                        group, False, dict(host._settings_manager.last_errors), None
                    )
                    return
                config_manager.load(candidate)
                host._logger.info(f"来源 {group} 已写入磁盘")

            record = host._settings_manager.last_probe or request.probes.get(group)
            gui_bridge.config_source_done.emit(group, True, {}, record)
        except Exception:
            gui_bridge.config_source_done.emit(request.group, False, {}, None)
            raise

    async def _settle_failure(self, reload_disk: bool = False) -> None:
        """校验没过的收尾

        - 需要时按盘上的值重载配置
        - 代理不通作废断连周期，配置问题只由向导说话
        """
        host = self._host
        if reload_disk:
            await host._settings_manager.execute()
        if not host._settings_manager.link_verified:
            # 代理不通或没探成：引擎失败源于代理，作废链路账，断连窗不踩配置向导
            link_report.reset("配置校验没过")
        self._resolved_proxy = None

        errors = host._settings_manager.last_errors
        if host._settings_manager.last_fatal or _is_token_fatal(errors):
            host._logger.error("Token 探测失败，弹窗引导退出")
            gui_bridge.request_notice.emit(CheckMessage.TOKEN_FATAL, True)
            return

        # 保持不就绪：数据修复完成前 EDIT 一律拦截
        self._request_setup(errors)

    async def _announce_config_ready(self) -> None:
        """向订阅了配置校验通过时机的件交代

        - 同时发就绪旗，界面据此收尾
        - 逐个跑订阅了校验通过时机的件
        - 跳过重启与真重启两支都走这里，订阅侧不必自己分辨
        """
        gui_bridge.config_ready_changed.emit(True)
        hooks = self._host._service_manager.runs_for(PlatformMoment.CONFIG_VERIFIED)
        call = self._host._service_manager.capability_call()
        for hook in hooks:
            await hook(call)

    def _current_identity(self) -> tuple[str, str]:
        """取当前对话身份

        - 由主人 id 与生效正文两项构成
        """
        item = owner_item()
        owner = config_manager.get(item, str) if item is not None else ""
        return (owner.strip(), applied_persona_text())

    async def commit_persona(self, text: str, source: str) -> None:
        """人设正文落盘并按正文变化清历史

        - 文件与存档都写成才换正文
        - 正文与生效值相同即只结清文件，不动历史
        - 换了正文才清历史，清完把新身份记成基准
        - 来源词只写进换版那条，正文没变即无来源可报
        """
        # 写坏一次不能出现正文新、文件旧
        if not save_persona_text(text) or not save_applied_persona(text):
            gui_bridge.request_notice.emit(
                DialogMessage.SETUP_PERSONA_FILE_CREATE_FAIL, False
            )
            return
        changed = text != applied_persona_text()
        load_persona_cache()
        if changed:
            await self.reset_identity()
        tip = (
            DialogMessage.PERSONA_APPLIED_RESET.format(source=source)
            if changed
            else DialogMessage.PERSONA_APPLIED_KEPT
        )
        gui_bridge.request_persona_applied.emit(tip)

    async def reset_identity(self) -> bool:
        """跑订阅了「身份变了」时机的件并记下新身份

        - 没件订阅「身份变了」即不清也不落基准，下一轮或读取侧对账补上
        """
        hooks = self._host._service_manager.runs_for(PlatformMoment.IDENTITY_CHANGED)
        if not hooks:
            return False
        call = self._host._service_manager.capability_call()
        for hook in hooks:
            await hook(call)
        self._last_identity = self._current_identity()
        return True

    async def _reset_stale_identity(self) -> None:
        """按身份变化清掉对话历史

        - 首次应用只记基准，不动已有历史
        """
        identity = self._current_identity()
        if self._last_identity is not None and self._last_identity != identity:
            await self.reset_identity()
            return
        self._last_identity = identity

    def _request_setup(self, field_errors: FieldErrors | None = None) -> None:
        """弹出强制配置向导"""
        self._host._logger.info("检测到配置有误，弹出配置向导...")
        gui_bridge.request_force_setup.emit(field_errors or {})

    def get_config_func(self) -> tuple[str, str | None]:
        """读取 Token 与生效 Proxy

        - 校验通过后返回生效通道，未校验时交 None 由适配器按直连起步
        """
        return get_token_func(), self._resolved_proxy
