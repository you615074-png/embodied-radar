"""根据 data/ 生成公开英文网站 site/（首页归档 + 每日页面）。"""
import html
import json

import markdown

from . import config

CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--accent:#4338ca}
@media (prefers-color-scheme:dark){:root{--bg:#0c0a09;--fg:#f5f5f4;--muted:#a8a29e;--card:#1c1917;--line:#292524;--accent:#a5b4fc}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 16px 80px}a{color:var(--accent)}
h1{font-size:28px;margin:0 0 4px;line-height:1.3}.sub{color:var(--muted);margin:0 0 28px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
.card h3{margin:0 0 6px;font-size:18px}.meta{color:var(--muted);font-size:14px}
.tag{display:inline-block;font-size:12px;padding:1px 8px;border:1px solid var(--line);border-radius:99px;margin-right:6px}
.try{border-left:3px solid var(--accent);padding:4px 12px;margin:12px 0}
.hot{border-color:#f59e0b}.hot h2{margin:0 0 4px;font-size:20px}
"""

KIND_EN = {"paper": "Paper", "repo": "Repo", "dataset": "Dataset", "model": "Model"}
TOPIC_EN = {"操作抓取": "Manipulation", "人形与足式": "Humanoids & legged", "VLA与基础模型": "VLA & foundation models",
            "世界模型与仿真": "World models & sim", "数据集": "Datasets", "导航与自动驾驶": "Navigation & driving",
            "硬件与本体": "Hardware", "强化学习": "RL", "其他": "Other"}


def e(s) -> str:
    return html.escape(str(s or ""))


def md(text: str) -> str:
    """模型写的 Markdown 先转义 HTML 再渲染，防止摘要或 README 里注入的脚本混进公开页面。"""
    return markdown.markdown(html.escape(text or "", quote=False))


def tags(x: dict) -> str:
    return (f'<span class="tag">{e(KIND_EN.get(x["kind"], x["kind"]))}</span>'
            f'<span class="tag">{e(TOPIC_EN.get(x.get("topic"), x.get("topic")))}</span>')


def byline() -> str:
    if not config.X_HANDLE:
        return ""
    h = e(config.X_HANDLE)
    return f' · by <a href="https://x.com/{h}">@{h}</a>'


def page(title: str, body: str) -> str:
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>')


def trend_card(t: dict | None, title: str) -> str:
    if not t:
        return ""
    streak = f' · #1 for {t["streak"]} days running' if t.get("streak", 1) > 1 else ""
    ev = "".join(f'<li><a href="{e(x["url"])}">{e(x["title"])}</a> <span class="meta">'
                 f'({e(KIND_EN.get(x["kind"], x["kind"]))})</span></li>' for x in t["evidence"])
    return (f'<div class="card hot"><div class="meta">🔥 {e(title)}{streak}</div>'
            f'<h2>{e(t["name_en"])}</h2><div>{e(t["one_liner_en"])}</div>'
            f'<div class="meta" style="margin-top:8px">Why we think so:</div><ul>{ev}</ul></div>')


def daily_page(d: dict) -> str:
    p = d["pick"]
    top = "".join(
        f'<div class="card"><div class="meta">#{i} · {tags(t)}</div>'
        f'<h3><a href="{e(t["url"])}">{e(t["title"])}</a></h3><div>{e(t["one_liner_en"])}</div>'
        f'<div class="meta">Try it: {e(t["how_to_try_en"])}</div></div>'
        for i, t in enumerate(d["top"], 1))
    body = (f'<p class="meta"><a href="../">← Embodied Radar</a> · {e(d["date"])}{byline()}</p>'
            f'<h1>{e(d["title_en"] or p["title"])}</h1>'
            f'<p class="sub">{tags(p)}<a href="{e(p["url"])}">{e(p["title"])}</a></p>'
            f'<div class="card">{md(d["summary_md"])}'
            f'<div class="try"><b>Try it without a robot:</b> {e(p["how_to_try_en"])}</div></div>'
            + trend_card(d.get("trend"), "Hottest technique this day") +
            f'<h2>Today\'s top {len(d["top"])}</h2>{top}')
    return page(f'{d["title_en"] or p["title"]} · Embodied Radar', body)


def build():
    (config.SITE / "daily").mkdir(parents=True, exist_ok=True)
    cards, latest_trend = [], None
    for f in sorted((config.DATA / "daily").glob("*.json"), reverse=True):
        d = json.loads(f.read_text())
        latest_trend = latest_trend or d.get("trend")
        (config.SITE / "daily" / f"{d['date']}.html").write_text(daily_page(d))
        p = d["pick"]
        cards.append(
            f'<div class="card"><div class="meta">{e(d["date"])} · {tags(p)}</div>'
            f'<h3><a href="daily/{e(d["date"])}.html">{e(d["title_en"] or p["title"])}</a></h3>'
            f'<div>{e(d["tagline_en"])}</div></div>')
    follow = (f' Follow along on X: <a href="https://x.com/{e(config.X_HANDLE)}">@{e(config.X_HANDLE)}</a>.'
              if config.X_HANDLE else "")
    body = ('<h1>🤖 Embodied Radar</h1><p class="sub">One new thing in embodied AI each day, explained by someone '
            'learning the field from scratch, with no lab and no robot. Each pick says whether you can try it '
            f'on a laptop. Picked from arXiv, Hugging Face and GitHub by an automated pipeline.{follow}</p>'
            + trend_card(latest_trend, "Hottest technique right now")
            + ("".join(cards) or '<p class="meta">Nothing yet</p>'))
    (config.SITE / "index.html").write_text(page("Embodied Radar", body))
    (config.SITE / ".nojekyll").write_text("")
