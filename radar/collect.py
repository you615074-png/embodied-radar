"""采集：arXiv 机器人论文、Hugging Face 每日论文 / 数据集 / 模型、GitHub 具身相关仓库。
所有来源统一成同一种条目：{id, kind, title, url, text, signals, heat, ...}。某个来源挂了只跳过它，不影响其他来源。"""
import base64
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from . import config

UA = "Mozilla/5.0 (embodied-radar; +https://github.com/you615074-png/embodied-radar)"
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": UA})
GH = requests.Session()
GH.headers.update({"Accept": "application/vnd.github+json", "User-Agent": UA,
                   "X-GitHub-Api-Version": "2022-11-28"})
if config.GITHUB_TOKEN:
    GH.headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

# 判断"是不是具身 / 机器人相关"的关键词，用于从 HF 每日论文和 GitHub trending 里挑
EMBODIED = re.compile(
    r"robot|embodied|manipulat|humanoid|locomotion|grasp|dexterous|quadruped|legged|"
    r"vision-language-action|\bvla\b|teleop|sim-?to-?real|lerobot|mujoco|isaac|ros2?\b|"
    r"autonomous (driving|vehicle)|drone|uav|navigation|world model|bimanual|gripper", re.I)


def get(url, *, session=HTTP, tries=4, **params):
    """带退避重试的 GET；404 返回 None。"""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=60)
            if r.ok:
                return r
            if r.status_code == 404:
                return None
            if r.status_code in (403, 429) and "api.github.com" in url:
                reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 30))
                time.sleep(min(max(reset - time.time(), 5), 120))
                continue
        except requests.RequestException:
            pass
        time.sleep(6 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}")


def heat_of(value: float, full: float) -> float:
    """对数热度 0-10：value 达到 full 时满分。"""
    return round(min(10, 10 * math.log10(1 + max(value, 0)) / math.log10(1 + full)), 2)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ---------- 论文 ----------

def arxiv_papers(days: int = 3) -> list[dict]:
    """arXiv cs.RO 最近几天的新论文（API 偶尔 503/429，get 会重试）。"""
    r = get("https://export.arxiv.org/api/query", search_query="cat:cs.RO",
            sortBy="submittedDate", sortOrder="descending", max_results=200)
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for e in ET.fromstring(r.text).findall("a:entry", ns):
        published = datetime.fromisoformat(e.find("a:published", ns).text.replace("Z", "+00:00"))
        if published < cutoff:
            continue
        aid = re.sub(r"v\d+$", "", e.find("a:id", ns).text.rsplit("/", 1)[-1])
        comment = e.find("arxiv:comment", ns)
        abstract = clean(e.find("a:summary", ns).text)
        extra = clean(comment.text) if comment is not None else ""
        out.append({
            "id": f"arxiv:{aid}", "kind": "paper", "arxiv_id": aid,
            "title": clean(e.find("a:title", ns).text),
            "url": f"https://arxiv.org/abs/{aid}",
            "authors": [clean(a.find("a:name", ns).text) for a in e.findall("a:author", ns)][:8],
            "created": published.date().isoformat(),
            "text": abstract + (f"\n\nComment: {extra}" if extra else ""),
            "has_code": bool(re.search(r"github\.com|project (page|website)|code (is )?(available|released)",
                                       abstract + extra, re.I)),
            "signals": {},
        })
    return out


def hf_daily_papers() -> list[dict]:
    """Hugging Face 每日论文（有社区点赞数，是论文热度的主要信号），只留具身相关的。"""
    out = []
    for day in range(0, 3):
        d = (date.today() - timedelta(days=day)).isoformat()
        r = get("https://huggingface.co/api/daily_papers", date=d, limit=100)
        for item in (r.json() if r else []):
            p = item.get("paper") or {}
            text = f"{p.get('title', '')} {p.get('summary', '')} {' '.join(p.get('ai_keywords') or [])}"
            if not p.get("id") or not EMBODIED.search(text):
                continue
            out.append({
                "id": f"arxiv:{p['id']}", "kind": "paper", "arxiv_id": p["id"],
                "title": clean(p.get("title")), "url": f"https://arxiv.org/abs/{p['id']}",
                "authors": [a.get("name", "") for a in p.get("authors", [])][:8],
                "created": (p.get("publishedAt") or "")[:10],
                "text": clean(p.get("summary")),
                "has_code": bool(p.get("githubRepo") or p.get("projectPage")),
                "code_url": p.get("githubRepo") or p.get("projectPage") or "",
                "signals": {"hf_upvotes": p.get("upvotes", 0), "github_stars": p.get("githubStars") or 0},
            })
    return out


# ---------- Hugging Face 数据集 / 模型 ----------

def hf_hub(kind: str) -> list[dict]:
    if kind == "dataset":
        r = get("https://huggingface.co/api/datasets", filter="LeRobot", sort="trendingScore", limit=30)
    else:
        r = get("https://huggingface.co/api/models", pipeline_tag="robotics", sort="trendingScore", limit=30)
    out = []
    for x in (r.json() if r else []):
        rid = x.get("id") or x.get("modelId")
        if not rid or x.get("private") or x.get("disabled"):
            continue
        prefix = "datasets/" if kind == "dataset" else ""
        tags = x.get("tags") or []
        lic = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
        out.append({
            "id": f"hf-{kind}:{rid}", "kind": kind, "title": rid,
            "url": f"https://huggingface.co/{prefix}{rid}", "hf_id": rid,
            "created": (x.get("createdAt") or x.get("lastModified") or "")[:10],
            "text": clean(x.get("description") or "")[:3000],
            "license": lic, "tags": [t for t in tags if ":" not in t][:12],
            "signals": {"hf_trending": x.get("trendingScore", 0), "hf_likes": x.get("likes", 0),
                        "downloads": x.get("downloads", 0)},
        })
    return out


def hf_card(item: dict, limit: int = 4000) -> str:
    """补抓 Hugging Face 卡片正文（README）。"""
    prefix = "datasets/" if item["kind"] == "dataset" else ""
    r = get(f"https://huggingface.co/{prefix}{item['hf_id']}/raw/main/README.md", tries=2)
    text = re.sub(r"^---.*?---", "", r.text, flags=re.S) if r else ""
    return strip_md(text)[:limit]


# ---------- GitHub ----------

def gh(path, **params):
    r = get(f"https://api.github.com{path}", session=GH, **params)
    return r.json() if r else None


def gh_item(i: dict) -> dict:
    return {
        "id": f"gh:{i['full_name']}", "kind": "repo", "title": i["full_name"], "url": i["html_url"],
        "full_name": i["full_name"], "created": (i.get("created_at") or "")[:10],
        "text": clean(i.get("description")), "license": (i.get("license") or {}).get("spdx_id") or "",
        "tags": i.get("topics") or [], "fork": i.get("fork", False), "archived": i.get("archived", False),
        "signals": {"stars": i.get("stargazers_count", 0)},
    }


GH_QUERIES = ["topic:robotics", "topic:embodied-ai", "topic:robot-learning", "topic:humanoid",
              "topic:vision-language-action", "topic:lerobot", "topic:manipulation",
              "robot in:name,description", "embodied in:name,description"]


def github_repos(today: date) -> list[dict]:
    since = (today - timedelta(days=30)).isoformat()
    repos = {}
    for q in GH_QUERIES:
        res = gh("/search/repositories", q=f"{q} created:>={since} stars:>=20 fork:false archived:false",
                 sort="stars", order="desc", per_page=50) or {}
        for i in res.get("items", []):
            repos.setdefault(i["full_name"], gh_item(i))
    # GitHub trending 日榜里和具身相关的
    try:
        html = get("https://github.com/trending", since="daily").text
        for art in BeautifulSoup(html, "html.parser").select("article.Box-row"):
            a, p = art.select_one("h2 a[href]"), art.select_one("p")
            name = a["href"].strip("/") if a else ""
            gained = art.find(string=re.compile(r"stars? today"))
            if name and EMBODIED.search(f"{name} {p.get_text() if p else ''}"):
                if name not in repos and (item := gh(f"/repos/{name}")):
                    repos[name] = gh_item(item)
                if name in repos and gained:
                    repos[name]["signals"]["trending_today"] = int(re.sub(r"\D", "", gained))
    except Exception as e:
        print(f"[采集] GitHub trending 失败：{e}")

    # 用前一天的 star 快照算日增
    snap_dir = config.DATA / "stars"
    snap_dir.mkdir(parents=True, exist_ok=True)
    prev = {}
    for back in (1, 2, 3):
        p = snap_dir / f"{(today - timedelta(days=back)).isoformat()}.json"
        if p.exists():
            prev, gap = json.loads(p.read_text()), back
            break
    now = datetime.now(timezone.utc).date()
    for name, r in repos.items():
        stars = r["signals"]["stars"]
        age = max((now - date.fromisoformat(r["created"])).days, 1) if r["created"] else 30
        rates = [stars / age, r["signals"].get("trending_today", 0)]
        if name in prev:
            rates.append((stars - prev[name]) / gap)
        r["signals"]["daily_rate"] = round(max(rates), 1)
    (snap_dir / f"{today.isoformat()}.json").write_text(
        json.dumps({n: r["signals"]["stars"] for n, r in sorted(repos.items())}, indent=0))
    return list(repos.values())


def strip_md(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text)  # 徽章
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # 图片
    text = re.sub(r"<img[^>]*>|<picture.*?</picture>", "", text, flags=re.S | re.I)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def github_readme(full_name: str, limit: int = 4000) -> str:
    res = gh(f"/repos/{full_name}/readme")
    if not res or "content" not in res:
        return ""
    return strip_md(base64.b64decode(res["content"]).decode("utf-8", errors="ignore"))[:limit]


# ---------- 汇总 ----------

def add_heat(it: dict):
    s = it["signals"]
    if it["kind"] == "paper":
        # 社区点赞 100 为满分；没上 HF 的论文只给一点基础分，有代码再加一点
        it["heat"] = max(heat_of(s.get("hf_upvotes", 0), 100), 1.0 + (1.0 if it.get("has_code") else 0))
    elif it["kind"] == "repo":
        it["heat"] = heat_of(s.get("daily_rate", 0), 300)
    else:
        it["heat"] = heat_of(s.get("hf_trending", 0), 100)


def collect(today: date) -> tuple[list[dict], dict]:
    t0 = time.time()
    sources = {"arxiv": arxiv_papers, "hf_papers": hf_daily_papers,
               "hf_datasets": lambda: hf_hub("dataset"), "hf_models": lambda: hf_hub("model"),
               "github": lambda: github_repos(today)}
    got, stats = {}, {}
    with ThreadPoolExecutor(len(sources)) as ex:
        futures = {name: ex.submit(fn) for name, fn in sources.items()}
        for name, f in futures.items():
            try:
                got[name] = f.result()
                stats[name] = len(got[name])
            except Exception as e:
                got[name], stats[name] = [], f"失败（{e}）"
                print(f"[采集] {name} 失败：{e}")

    items = {}
    # HF 每日论文放在 arXiv 后面合并：同一篇论文以 HF 的数据（点赞、代码链接）为准，摘要保留更长的
    for it in got["arxiv"] + got["hf_papers"] + got["hf_datasets"] + got["hf_models"] + got["github"]:
        old = items.get(it["id"])
        if old:
            it["text"] = max(old["text"], it["text"], key=len)
            it["has_code"] = old.get("has_code") or it.get("has_code")
            it["signals"] = {**old["signals"], **it["signals"]}
        items[it["id"]] = it
    for it in items.values():
        add_heat(it)
    print(f"[采集] {stats}，去重后 {len(items)} 个，用时 {time.time() - t0:.0f}s")
    return sorted(items.values(), key=lambda i: i["heat"], reverse=True), stats


def enrich(it: dict):
    """给送去打分的条目补正文：仓库补 README，HF 数据集 / 模型补卡片。论文用摘要就够了。"""
    try:
        if it["kind"] == "repo":
            it["text"] = f"{it['text']}\n\n{github_readme(it['full_name'])}".strip()
        elif it["kind"] in ("dataset", "model") and len(it["text"]) < 1500:
            it["text"] = f"{it['text']}\n\n{hf_card(it)}".strip()
    except Exception as e:
        print(f"[采集] 补正文失败 {it['id']}：{e}")
