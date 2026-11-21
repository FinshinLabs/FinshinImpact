"""上下文预算测试

- 字符折算按中文与其余两套系数
- 每条消息的打包开销由端点读数倒推
- 窗口超线从最旧一组问答丢起，人设行始终保留
- 丢空仍超线即交出空历史与超线读数
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from bundled.AI import utils  # noqa: E402
from finshin_sdk.domain import ChatRole  # noqa: E402
from finshin_sdk.dto import MessageDTO  # noqa: E402


def _rounds(count: int, text: str = "说一句") -> tuple[MessageDTO, ...]:
    """构造 count 轮问答"""
    rows: list[MessageDTO] = []
    for index in range(count):
        rows.append(
            MessageDTO(
                role=ChatRole.USER,
                content=f"{text}{index}",
                sender_id=f"{100 + index % 2}",
                sender_name=f"人名{index % 2}",
            )
        )
        rows.append(MessageDTO(role=ChatRole.ASSISTANT, content=f"回{index}" * 4))
    return tuple(rows)


def _pair(name: str) -> tuple[MessageDTO, ...]:
    """按给定显示名构造一轮问答"""
    return (
        MessageDTO(
            role=ChatRole.USER, content="说一句", sender_id="100", sender_name=name
        ),
        MessageDTO(role=ChatRole.ASSISTANT, content="回话"),
    )


class TestTokenEstimate(unittest.TestCase):
    def test_cjk_and_ascii_use_different_rates(self) -> None:
        """中文与英文各按自己的系数折算"""
        self.assertEqual(utils._estimate_tokens("你好世界"), 2)
        self.assertEqual(utils._estimate_tokens("abcdefgh"), 2)

    def test_window_sum_includes_all_parts(self) -> None:
        """窗口估算把人设、历史与问句一起计入"""
        short = (MessageDTO(role=ChatRole.SYSTEM, content="人设"), *_rounds(1))
        long = (MessageDTO(role=ChatRole.SYSTEM, content="人设正文加长"), *_rounds(1))

        self.assertGreater(
            utils._estimate_window(long, "新问"), utils._estimate_window(short, "新问")
        )
        self.assertGreater(
            utils._estimate_window(short, "新问"), utils._estimate_window(short, "")
        )

    def test_sender_mark_prices_in_by_length(self) -> None:
        """正文一字不差，发言人名字越长折算的体量越大"""
        window = (MessageDTO(role=ChatRole.SYSTEM, content="人设"),)
        short = utils._estimate_window((*window, *_pair("甲")), "问")
        long = utils._estimate_window((*window, *_pair("甲乙丙丁戊")), "问")
        self.assertGreater(long, short)

    def test_turn_overhead_learns_from_reading(self) -> None:
        """每条消息的打包开销由端点读数倒推，下一轮按条数补上"""
        window = (MessageDTO(role=ChatRole.SYSTEM, content="人设"), *_rounds(2))
        ask = "[人名0|100]说一句"
        turns = utils.build_turns(persona="人设", history=window[1:], thisinput=ask)
        content = sum(utils._estimate_tokens(turn["content"]) for turn in turns)
        actual = content + len(turns) * 8
        utils.learn_turn_overhead(turns, actual)
        self.assertEqual(utils._estimate_window(window, ask), actual)

    def test_reading_below_content_keeps_overhead(self) -> None:
        """读数不大于正文折算即不刷新，倒推不出负数"""
        window = (MessageDTO(role=ChatRole.SYSTEM, content="人设"), *_rounds(1))
        before = utils._estimate_window(window, "[人名0|100]问")
        turns = utils.build_turns(
            persona="人设", history=window[1:], thisinput="[人名0|100]问"
        )
        utils.learn_turn_overhead(turns, 0)
        self.assertEqual(utils._estimate_window(window, "[人名0|100]问"), before)


class TestFitHistory(unittest.TestCase):
    def test_drops_oldest_rounds_until_under_limit(self) -> None:
        """从最旧一组问答丢起，留下尾部整轮"""
        history = _rounds(3)
        prompt = "[人名0|100]新问"
        one_round = utils._estimate_window(
            (MessageDTO(role=ChatRole.SYSTEM, content="人设"), *_rounds(1)), prompt
        )

        kept, tokens = utils.fit_history("人设", history, prompt, one_round)

        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].content, "说一句2")
        self.assertLessEqual(tokens, one_round)

    def test_keeps_all_when_within_limit(self) -> None:
        """没超线一字不动"""
        history = _rounds(2)
        prompt = "问"

        kept, _ = utils.fit_history("人设", history, prompt, 10**9)

        self.assertEqual(kept, history)

    def test_empties_history_when_still_over(self) -> None:
        """丢空历史仍超线即交出空历史与超线读数"""
        history = _rounds(3)
        prompt = "问"

        kept, tokens = utils.fit_history("人设", history, prompt, 1)

        self.assertEqual(kept, ())
        self.assertGreater(tokens, 1)


class TestWindowCap(unittest.TestCase):
    def test_persona_row_kept_and_cap_applied(self) -> None:
        """窗口上限放宽到常量值，人设行始终占首位"""
        history = (MessageDTO(role=ChatRole.SYSTEM, content="人设"), *_rounds(200))
        window = utils.open_window("人设", history)
        self.assertEqual(window[0].content, "人设")
        cap = utils._MAX_CONTEXT_MESSAGES - 1 - utils._ROUND_ROWS
        self.assertLessEqual(len(window) - 1, cap)
        self.assertGreaterEqual(len(window) - 1, cap - 1)
        self.assertEqual((len(window) - 1) % utils._ROUND_ROWS, 0)
        self.assertEqual(window[1].role, ChatRole.USER)


class TestTurnAssembly(unittest.TestCase):
    def test_persona_then_history_then_prompt(self) -> None:
        """人设轮后直接是历史，当前问句在末尾"""
        turns = utils.build_turns(
            persona="人设",
            history=_rounds(1),
            thisinput="[人名0|100]再说一遍",
        )
        self.assertEqual(turns[0]["role"], ChatRole.SYSTEM)
        self.assertEqual(turns[1]["role"], ChatRole.USER)
        self.assertEqual(turns[2]["role"], ChatRole.ASSISTANT)
        self.assertEqual(turns[-1]["role"], ChatRole.USER)
        self.assertTrue(turns[-1]["content"].endswith("再说一遍"))


if __name__ == "__main__":
    unittest.main()
