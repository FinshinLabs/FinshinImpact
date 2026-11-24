"""检查结论行短句"""

from skin.messages import CheckMessage, DialogMessage

from ..config import FieldErrors


def failure_note(detail: str, field_errors: FieldErrors) -> str:
    """结论行失败那一句

    - 有结论句先用它，没有按标红字段数出句
    - 一个字段错都没有即回落未通过提示
    """
    if detail:
        return detail
    if field_errors:
        return CheckMessage.VERIFY_ADVICE_FAIL.format(n=len(field_errors))
    return DialogMessage.CHECK_PROBE_HEAD_FAIL
