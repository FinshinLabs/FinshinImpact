"""旧实例配置迁移

- 启动器与引导层共用的入口
"""

from ._runner import run_all, run_instance

__all__ = [
    # 启动器与引导层入口
    "run_all",
    "run_instance",
]
