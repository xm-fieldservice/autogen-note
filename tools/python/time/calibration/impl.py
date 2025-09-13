import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

# 简化时区处理：目前仅支持 Asia/Shanghai（UTC+8）
_TZ_MAP = {
    "Asia/Shanghai": timezone(timedelta(hours=8)),
}

_WEEKDAY_MAP = {
    0: "星期一",
    1: "星期二",
    2: "星期三",
    3: "星期四",
    4: "星期五",
    5: "星期六",
    6: "星期日",
}


def _get_tz(tz_name: str) -> timezone:
    return _TZ_MAP.get(tz_name, timezone(timedelta(hours=8)))


def _wk_str(dt: datetime) -> str:
    return _WEEKDAY_MAP.get(dt.weekday(), "")


def calibrate(reference: str | None = None, mode: str = "fixed", timezone_name: str = "Asia/Shanghai") -> Dict[str, Any]:
    tz = _get_tz(timezone_name)
    if mode == "realtime" or not reference:
        base = datetime.now(tz)
    else:
        # 解析 reference（允许无偏移，默认按 tz 补齐）
        try:
            if reference.endswith("Z"):
                base = datetime.fromisoformat(reference.replace("Z", "+00:00")).astimezone(tz)
            else:
                dt = datetime.fromisoformat(reference)
                base = dt if dt.tzinfo else dt.replace(tzinfo=tz)
        except Exception:
            base = datetime.now(tz)
    return {
        "reference_iso": base.isoformat(),
        "weekday": _wk_str(base),
        "tz": timezone_name,
        "now_human": base.strftime("%Y-%m-%d %H:%M:%S ") + _wk_str(base),
    }


def today(reference_iso: str, timezone_name: str = "Asia/Shanghai") -> Dict[str, Any]:
    tz = _get_tz(timezone_name)
    try:
        dt = datetime.fromisoformat(reference_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        dt = dt.astimezone(tz)
    except Exception:
        dt = datetime.now(tz)
    d = dt.date()
    out = datetime(d.year, d.month, d.day, tzinfo=tz)
    return {"date_iso": out.isoformat(), "weekday": _wk_str(out)}


_REL_PATTERNS = [
    (re.compile(r"^(今天)$"), 0),
    (re.compile(r"^(明天)$"), 1),
    (re.compile(r"^(后天)$"), 2),
    (re.compile(r"^(昨天)$"), -1),
    (re.compile(r"^(前天)$"), -2),
    (re.compile(r"^(\d+)天后$"), "+N"),
    (re.compile(r"^(\d+)天前$"), "-N"),
]


def _parse_offset(expr: str) -> int | None:
    s = expr.strip()
    for pat, val in _REL_PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        if isinstance(val, int):
            return val
        if val == "+N":
            return int(m.group(1))
        if val == "-N":
            return -int(m.group(1))
    return None


def add_days(reference_iso: str, days: int, timezone_name: str = "Asia/Shanghai") -> Dict[str, Any]:
    tz = _get_tz(timezone_name)
    try:
        base = datetime.fromisoformat(reference_iso)
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        base = base.astimezone(tz)
    except Exception:
        base = datetime.now(tz)
    tgt = base + timedelta(days=int(days))
    return {"date_iso": tgt.isoformat(), "weekday": _wk_str(tgt)}


def resolve_relative(expr: str, reference_iso: str, timezone_name: str = "Asia/Shanghai") -> Dict[str, Any]:
    tz = _get_tz(timezone_name)
    try:
        base = datetime.fromisoformat(reference_iso)
        if base.tzinfo is None:
            base = base.replace(tzinfo=tz)
        base = base.astimezone(tz)
    except Exception:
        base = datetime.now(tz)
    off = _parse_offset(expr)
    if off is None:
        # 未识别，返回基准日
        d = base
    else:
        d = base + timedelta(days=off)
    return {
        "absolute_iso": d.isoformat(),
        "human": d.strftime("%Y-%m-%d %H:%M:%S ") + _wk_str(d),
        "offset_days": off if off is not None else 0,
    }
