"""DeepSeek 谷时判断。只用标准库，工作流在装依赖之前就能调用。

峰时：周一到周五 UTC 01:00-04:00、06:00-10:00（北京 09-12 点、14-18 点），其余时间都是谷时，周末全天谷时。
来源：https://api-docs.deepseek.com/quick_start/pricing（2026-11 核对）。
中国法定节假日官方也算谷时，这里不判断，按峰时处理，宁可少跑一次也不多花钱。

用法（工作流里）：python radar/offpeak.py --event schedule
在 $GITHUB_OUTPUT 里写 run=true/false，并打印原因。
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PEAK_HOURS_UTC = [(1, 4), (6, 10)]
BJ = timezone(timedelta(hours=8))
# 开跑时要保证这段时间内都不会进入峰时（实际一次运行 1-15 分钟）
RUN_MARGIN = timedelta(minutes=40)
# 定时运行只在 UTC 00:00-15:00（北京 08:00-23:00）开跑：
# 日报日期按北京时间算，不会跨天；最晚的一次也能在太平洋时间早上 7 点前送达
RUN_WINDOW_UTC = (0, 15)


def is_peak(now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now.weekday() >= 5:
        return False
    return any(a <= now.hour < b for a, b in PEAK_HOURS_UTC)


def can_start(now: datetime | None = None, *, window: bool = True) -> tuple[bool, str]:
    """现在开跑是否安全：整个运行期间都在谷时，定时运行还要在每日窗口内。"""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if window and not RUN_WINDOW_UTC[0] <= now.hour < RUN_WINDOW_UTC[1]:
        return False, f"UTC {now:%H:%M} 不在每日运行窗口（UTC {RUN_WINDOW_UTC[0]:02d}-{RUN_WINDOW_UTC[1]:02d} 点）"
    t = now
    while t <= now + RUN_MARGIN:
        if is_peak(t):
            return False, f"UTC {now:%H:%M} 开跑会碰到 DeepSeek 峰时（UTC {t:%H:%M}）"
        t += timedelta(minutes=5)
    return True, f"UTC {now:%H:%M} 是 DeepSeek 谷时"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default="schedule")
    args = ap.parse_args()
    scheduled = args.event == "schedule"
    ok, why = can_start(window=scheduled)
    if ok and scheduled:
        ts = datetime.now(BJ).date().isoformat()
        if (Path(__file__).resolve().parent.parent / "data" / "daily" / f"{ts}.json").exists():
            ok, why = False, f"{ts} 的日报已经生成过了"
    print(f"[{'开跑' if ok else '跳过'}] {why}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"run={'true' if ok else 'false'}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
