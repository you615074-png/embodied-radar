"""规则过滤（不调用大模型）和历史记录。"""
import json
import re
from datetime import date, timedelta

from . import config

LIST_BAD = re.compile(r"(^|[-_/])(awesome|tutorials?|course|roadmap|papers?-list|reading-list)([-_]|$)|"
                      r"curated list|a list of|collection of (papers|resources|links)", re.I)

HISTORY = config.DATA / "history.json"


def load_history() -> dict:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return {"picks": [], "top": {}, "scores": {}}


def save_history(h: dict):
    HISTORY.write_text(json.dumps(h, ensure_ascii=False, indent=1))


def rule_filter(items: list[dict], h: dict, today: date) -> tuple[list[dict], dict]:
    picked = {p["id"] for p in h["picks"]}
    cutoff = (today - timedelta(days=config.TOP_REPEAT_DAYS)).isoformat()
    recent_top = {i for i, d in h["top"].items() if d >= cutoff and d != today.isoformat()}
    kept, dropped = [], {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for it in items:
        if it.get("fork") or it.get("archived"):
            drop("fork 或已归档")
        elif it["id"] in picked:
            drop("以前已精选")
        elif it["id"] in recent_top:
            drop("近 7 天已上榜")
        elif LIST_BAD.search(it["title"]) or LIST_BAD.search(it["text"][:300]):
            drop("列表 / 教程类")
        elif len(it["text"]) < 80 and it["kind"] in ("paper", "repo"):  # 数据集 / 模型稍后补卡片
            drop("介绍太短")
        else:
            kept.append(it)
    # 每类按热度取前 N 个（论文里有代码的优先）
    out, count = [], {}
    for it in sorted(kept, key=lambda i: (i["heat"], bool(i.get("has_code"))), reverse=True):
        k = it["kind"]
        if count.get(k, 0) < config.MAX_PER_KIND[k]:
            out.append(it)
            count[k] = count.get(k, 0) + 1
    return out, dropped
