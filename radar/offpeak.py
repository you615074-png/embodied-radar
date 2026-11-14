"""DeepSeek 谷时判断。只用标准库，工作流在装依赖之前就能调用。

峰时：周一到周五 UTC 01:00-04:00、06:00-10:00（北京 09-12 点、14-18 点），其余时间都是谷时，周末全天谷时。
来源：https://api-docs.deepseek.com/quick_start/pricing（2026-11 核对）。
中国法定节假日官方也算谷时，这里不判断，按峰时处理，宁可少跑一次也不多花钱。

用法（工作流里）：python radar/offpeak.py [--skip-if-done]
在 $GITHUB_OUTPUT 里写 run=true/false，并打印原因。
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PEAK_HOURS_UTC = [(1, 4), (6, 10)]
# 日报的"一天"从 UTC 10:00（北京 18:00，DeepSeek 峰时结束）开始算，而不是北京时间零点。
# 峰时结束后第一个落进来的定时任务生成这一期，之后到下一个 UTC 10:00 之前的触发都算同一期，
# 晚到的触发不会抢先生成"明天"那一期。
EDITION_START_UTC = 10
# 开跑时要保证这段时间内都不会进入峰时（实际一次运行 1-15 分钟）
RUN_MARGIN = timedelta(minutes=40)


def is_peak(now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now.weekday() >= 5:
        return False
    return any(a <= now.hour < b for a, b in PEAK_HOURS_UTC)


def edition_date(now: datetime | None = None) -> date:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return (now - timedelta(hours=EDITION_START_UTC)).date()


def can_start(now: datetime | None = None) -> tuple[bool, str]:
    """现在开跑是否安全：整个运行期间都在谷时。"""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    t = now
    while t <= now + RUN_MARGIN:
        if is_peak(t):
            return False, f"UTC {now:%H:%M} 开跑会碰到 DeepSeek 峰时（UTC {t:%H:%M}）"
        t += timedelta(minutes=5)
    return True, f"UTC {now:%H:%M} 是 DeepSeek 谷时"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-if-done", action="store_true", help="这一期日报已生成就跳过")
    ap.add_argument("--print-date", action="store_true", help="只打印当前期号日期")
    args = ap.parse_args()
    ts = edition_date().isoformat()
    if args.print_date:
        print(ts)
        return
    ok, why = can_start()
    if ok and args.skip_if_done:
        if (Path(__file__).resolve().parent.parent / "data" / "daily" / f"{ts}.json").exists():
            ok, why = False, f"{ts} 这一期已经生成过了"
    print(f"[{'开跑' if ok else '跳过'}] {why}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"run={'true' if ok else 'false'}\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
