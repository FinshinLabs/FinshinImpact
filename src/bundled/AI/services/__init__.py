"""AI 服务门面

- 对话分发、任务处理、清理循环与停机交代出口
"""

from ._ai_chat import chat_task_handler, handle_ai_chat
from ._cleanup import cleanup_loop, wake_cleanup
from ._receipt import report_lost_tasks
