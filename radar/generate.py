"""生成日报内容（公开英文介绍 + 推文草稿 + 私人中文学习笔记）。"""
import json
from string import Template

from . import config, llm
from .score import KIND_ZH, prompt


def write_content(pick: dict, others: list[dict]) -> dict:
    e = pick["eval"]
    lines = [f"- [{KIND_ZH[o['kind']]}] {o['title']}：{o['eval'].get('one_liner', '')}" for o in others]
    user = Template(prompt("content.user.md")).safe_substitute(
        kind_zh=KIND_ZH[pick["kind"]], title=pick["title"], url=pick["url"],
        authors=", ".join(pick.get("authors") or []) or "（未知）", license=pick.get("license") or "（未标注）",
        signals=json.dumps(pick["signals"], ensure_ascii=False), topic=e.get("topic", ""),
        one_liner=e.get("one_liner", ""), how_to_try=e.get("how_to_try", ""),
        concepts="；".join(f"{c['term']}（{c.get('zh', '')}）" for c in e.get("concepts", [])) or "无",
        red_flags="；".join(e.get("red_flags") or []) or "无", reason=e.get("reason", ""),
        others="\n".join(lines) or "（无）", text=pick["text"][:5000])
    messages = [{"role": "system", "content": prompt("content.system.md")},
                {"role": "user", "content": user}]
    for attempt in range(1, 4):
        try:
            data = llm.parse_json(llm.chat(messages, config.MODEL_WRITE, json_mode=True, max_tokens=8000))
            break
        except ValueError as err:
            print(f"[文案] 第 {attempt} 次返回的 JSON 无效：{err}")
    else:  # 三次都失败：用打分结果拼一个简版，保证日报照常发出
        data = {"headline": e.get("one_liner", "")[:20], "title_en": pick["title"][:70],
                "tagline_en": e.get("one_liner_en", ""), "summary_md": e.get("one_liner_en", ""),
                "explainer_md": f"（今天的学习笔记生成失败）\n\n{e.get('reason', '')}",
                "tweet": "", "thread": []}
    for k in ("headline", "title_en", "tagline_en", "summary_md", "explainer_md", "tweet"):
        data[k] = str(data.get(k) or "")
    thread = data.get("thread") or []
    data["thread"] = [str(t) for t in thread] if isinstance(thread, list) else [str(thread)]
    return data
