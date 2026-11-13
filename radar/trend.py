"""每天回答一个问题：具身智能现在最新最热的技术是什么。

依据是今天打过分的全部候选（不只是 Top 5），由模型归纳出被多条内容同时推动的技术方向。
失败时返回 None，不影响日报的其他部分。
"""
import json
from datetime import date, timedelta
from string import Template

from . import config, llm
from .score import KIND_ZH, prompt

MAX_ITEMS = 60          # 最多把多少条候选交给模型
KEEP_DAYS = 30          # history["trends"] 保留多少天


def find_trend(ranked: list[dict], history: dict, today: date) -> dict | None:
    # 按热度和重要性挑出最有信号的候选，热门但综合分不高的论文也要保留
    pool = sorted(ranked, key=lambda i: i["heat"] + i["eval"]["scores"]["significance"], reverse=True)[:MAX_ITEMS]
    lines = []
    for n, it in enumerate(pool, 1):
        ev = it["eval"]
        terms = "、".join(c["term"] for c in ev.get("concepts", [])) or "无"
        lines.append(f"[{n}] {KIND_ZH[it['kind']]} · {it['title'][:120]} · {ev.get('topic', '')} · "
                     f"{ev.get('one_liner', '')} · {terms} · 热度 {it['heat']} · 重要性 {ev['scores']['significance']}")
    trends = history.setdefault("trends", [])
    recent = [t for t in trends if t["date"] >= (today - timedelta(days=7)).isoformat() and t["date"] < today.isoformat()]
    user = Template(prompt("trend.user.md")).safe_substitute(
        date=today.isoformat(), items="\n".join(lines),
        recent="\n".join(f"- {t['date']}：{t['name_en']}（{t['name_zh']}）" for t in recent) or "（还没有）")
    messages = [{"role": "system", "content": prompt("trend.system.md")}, {"role": "user", "content": user}]
    for attempt in range(1, 3):
        try:
            data = llm.parse_json(llm.chat(messages, config.MODEL_WRITE, json_mode=True, max_tokens=6000))
            if data.get("name_en") and data.get("name_zh"):
                break
            raise ValueError("缺少技术名")
        except ValueError as err:
            print(f"[热门技术] 第 {attempt} 次返回无效：{err}")
    else:
        return None

    evidence = []
    for n in data.get("evidence") or []:
        if isinstance(n, int) and 1 <= n <= len(pool) and pool[n - 1] not in evidence:
            evidence.append(pool[n - 1])
    trend = {
        "name_en": str(data["name_en"]).strip(), "name_zh": str(data["name_zh"]).strip(),
        "one_liner": str(data.get("one_liner") or ""), "one_liner_en": str(data.get("one_liner_en") or ""),
        "momentum": str(data.get("momentum") or ""),
        "evidence": [{"kind": it["kind"], "title": it["title"], "url": it["url"],
                      "one_liner_en": it["eval"].get("one_liner_en", "")} for it in evidence[:6]],
        "runner_ups": [{k: str(r.get(k) or "") for k in ("name_zh", "name_en", "why")}
                       for r in (data.get("runner_ups") or []) if isinstance(r, dict)][:2],
    }
    # 连续几天都是同一个技术
    streak = 1
    for t in reversed(recent):
        if t["name_en"].lower() != trend["name_en"].lower():
            break
        streak += 1
    trend["streak"] = streak

    history["trends"] = [t for t in trends if t["date"] != today.isoformat()
                         and t["date"] >= (today - timedelta(days=KEEP_DAYS)).isoformat()]
    history["trends"].append({"date": today.isoformat(), "name_en": trend["name_en"], "name_zh": trend["name_zh"]})
    print(f"[热门技术] {trend['name_zh']}（{trend['name_en']}），{trend['momentum']}，连续 {streak} 天，"
          f"证据 {len(trend['evidence'])} 条")
    return {**trend, "explainer_md": str(data.get("explainer_md") or "")}
