"""视图公共件门面

- 代发构造工厂、按钮装配件、自绘件、循环滚动的长文案标签、布局边距与窗层序工具
- 代发弹窗基类与版本清单配正文两栏
"""

from ._buttons import ButtonBar, ButtonSpec
from ._check import TickedCheckBox
from ._dialog import BaseDialog
from ._factory import fill_combo, make_button, make_combo
from ._layout import clear_layout, make_scroller, set_margins
from ._list import ThemedList
from ._marquee import MarqueeLabel
from ._release_panes import PaneEntry, ReleasePanes
from ._stack import bring_front, follow_above
