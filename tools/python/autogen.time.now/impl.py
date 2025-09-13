from datetime import datetime, timedelta, timezone
from typing import Dict, Any

_TZ_MAP = {
    "Asia/Shanghai": timezone(timedelta(hours=8)),
}

def _get_tz(tz_name: str) -> timezone:
    return _TZ_MAP.get(tz_name, timezone(timedelta(hours=8)))


def now(timezone_name: str = "Asia/Shanghai") -> Dict[str, Any]:
    tz = _get_tz(timezone_name)
    dt = datetime.now(tz)
    weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
    return {
        "now_iso": dt.isoformat(),
        "human": dt.strftime("%Y-%m-%d %H:%M:%S ") + weekday_map.get(dt.weekday(), ""),
        "tz": timezone_name,
    }
