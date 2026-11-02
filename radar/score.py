"""DeepSeek 打分 + 综合排序。"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from string import Template

from . import config, llm

KEYS = ["significance", "explainability", "wow", "playable", "openness", "learning_value"]
WEIGHTS = {"significance": 0.22, "explainability": 0.13, "wow": 0.12, "playable": 0.18,
           "openness": 0.10, "learning_value": 0.10}
HEAT_WEIGHT = 0.15
KIND_ZH = {"paper": "论文", "repo": "开源仓库", "dataset": "数据集", "model": "模型"}
# 评分标准有改动时 +1，旧缓存会自动重新打分
RUBRIC_VERSION = 1


def prompt(name: str) -> str:
    return (config.PROMPTS / name).read_text()


def score_one(it: dict) -> dict:
    user = Template(prompt("score.user.md")).safe_substitute(
        kind_zh=KIND_ZH[it["kind"]], title=it["title"], url=it["url"],
        authors=", ".join(it.get("authors") or []) or "（未知）", created=it.get("created") or "（未知）",
        license=it.get("license") or "（未标注）", signals=json.dumps(it["signals"], ensure_ascii=False),
        has_code="是" if it.get("has_code") or it["kind"] != "paper" else "否",
        tags=", ".join(it.get("tags") or []) or "（无）", text=it["text"][:5000])
    messages = [{"role": "system", "content": prompt("score.system.md")},
                {"role": "user", "content": user}]
    try:
        data = llm.parse_json(llm.chat(messages, config.MODEL_SCORE, json_mode=True, max_tokens=1500))
    except ValueError:  # JSON 偶尔不合法，重试一次
        data = llm.parse_json(llm.chat(messages, config.MODEL_SCORE, json_mode=True, max_tokens=1500))
    s = data.get("scores") or {}
    data["scores"] = {k: max(1, min(10, int(s.get(k, 5) or 5))) for k in KEYS}
    data["red_flags"] = data.get("red_flags") or []
    data["concepts"] = [c for c in (data.get("concepts") or []) if isinstance(c, dict) and c.get("term")][:3]
    return data


def aggregate(it: dict, recent_topics: set) -> dict:
    s = it["eval"]["scores"]
    final = sum(WEIGHTS[k] * s[k] for k in KEYS) + HEAT_WEIGHT * it["heat"]
    penalty = 0.6 if it["eval"].get("topic") in recent_topics else 0
    return {"final": round(final - penalty, 2), "topic_penalty": penalty, **s, "heat": it["heat"]}


def pick_top(ranked: list[dict], n: int) -> list[dict]:
    """按综合分取前 n 个；同一类型、同一主题各最多 2 个，保证每天的榜单有变化。"""
    top, kinds, topics = [], {}, {}
    for it in ranked:
        k, t = it["kind"], it["eval"].get("topic") or "其他"
        if kinds.get(k, 0) >= config.TOP_PER_KIND or topics.get(t, 0) >= config.TOP_PER_TOPIC:
            continue
        top.append(it)
        kinds[k], topics[t] = kinds.get(k, 0) + 1, topics.get(t, 0) + 1
        if len(top) == n:
            break
    # 论文是领域进展的主要来源，但"可玩"和"开放"天然吃亏：没有论文上榜时，用最好的论文换掉最后一名
    best_paper = next((it for it in ranked if it["kind"] == "paper"), None)
    if best_paper and best_paper not in top and not any(t["kind"] == "paper" for t in top):
        top[-1:] = [best_paper]
    return top


def score_all(items: list[dict], history: dict, today: date) -> list[dict]:
    """对候选打分，7 天内打过分的复用缓存。返回按综合分排序的列表。"""
    cache = history["scores"]
    cutoff = (today - timedelta(days=config.SCORE_CACHE_DAYS)).isoformat()

    def fresh(i):
        c = cache.get(i, {})
        return c.get("date", "") >= cutoff and c.get("v") == RUBRIC_VERSION

    todo = [it for it in items if not fresh(it["id"])]
    for it in items:
        if it not in todo:
            it["eval"] = cache[it["id"]]["eval"]

    def run(it):
        try:
            it["eval"] = score_one(it)
            cache[it["id"]] = {"date": today.isoformat(), "v": RUBRIC_VERSION, "eval": it["eval"]}
        except Exception as e:
            print(f"[打分] {it['id']} 失败：{e}")

    with ThreadPoolExecutor(config.LLM_CONCURRENCY) as ex:
        list(ex.map(run, todo))
    print(f"[打分] 新打分 {len(todo)} 个，复用缓存 {len(items) - len(todo)} 个")

    for i in [i for i, v in cache.items() if v["date"] < cutoff]:
        del cache[i]

    recent = {p["topic"] for p in history["picks"]
              if p["date"] >= (today - timedelta(days=config.RECENT_TOPIC_DAYS)).isoformat()}
    scored = [it for it in items if "eval" in it]
    for it in scored:
        it["score"] = aggregate(it, recent)
    return sorted(scored, key=lambda i: i["score"]["final"], reverse=True)
