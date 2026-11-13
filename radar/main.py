"""每日流程入口：python -m radar.main [--dry-run] [--limit N] [--skip-if-done]"""
import argparse
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import collect, config, filters, generate, llm, mailer, offpeak, score, site, trend


def public_item(it: dict) -> dict:
    ev = it["eval"]
    return {
        "id": it["id"], "kind": it["kind"], "title": it["title"], "url": it["url"],
        "authors": it.get("authors") or [], "license": it.get("license") or "",
        "code_url": it.get("code_url", ""), "signals": it["signals"],
        "topic": ev.get("topic", ""), "one_liner": ev.get("one_liner", ""),
        "one_liner_en": ev.get("one_liner_en", ""), "how_to_try": ev.get("how_to_try", ""),
        "how_to_try_en": ev.get("how_to_try_en", ""), "reason": ev.get("reason", ""),
        "red_flags": ev.get("red_flags") or [], **it["score"],
    }


def update_glossary(items: list[dict], today: str) -> list[dict]:
    """把今天出现的术语记进 data/glossary.json，返回第一次出现的那些。"""
    path = config.DATA / "glossary.json"
    glossary = json.loads(path.read_text()) if path.exists() else {}
    new = []
    for it in items:
        for c in it["eval"].get("concepts", []):
            key = c["term"].strip().lower()
            if key and key not in glossary:
                glossary[key] = {**c, "first_seen": today, "source": it["id"]}
                new.append(c)
    path.write_text(json.dumps(glossary, ensure_ascii=False, indent=1))
    return new


def run(args) -> None:
    today = datetime.now(config.BJ).date()
    ts = today.isoformat()
    peak_note = ("⚠️ 本次运行处于 DeepSeek 峰时（全价）" if llm.is_peak()
                 else "✅ 本次运行处于 DeepSeek 谷时（半价）")
    print(f"[开始] {ts}，{peak_note}，后端 {config.LLM_BACKEND}")
    if args.skip_if_done and (config.DATA / "daily" / f"{ts}.json").exists():
        print(f"[跳过] {ts} 的日报已经生成过了")
        return
    ok, why = offpeak.can_start(window=args.skip_if_done)
    if config.LLM_BACKEND == "api" and not ok and not os.getenv("ALLOW_PEAK"):
        print(f"[跳过] {why}")
        return

    history = filters.load_history()
    # 同一天重复运行时，先撤销当天的记录
    history["picks"] = [p for p in history["picks"] if p["date"] != ts]
    history["top"] = {i: d for i, d in history["top"].items() if d != ts}

    items, source_stats = collect.collect(today)
    cands, dropped = filters.rule_filter(items, history, today)
    if args.limit:
        cands = cands[:args.limit]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(collect.enrich, cands))
    short = [c for c in cands if len(c["text"]) < 80]
    if short:
        dropped["介绍太短"] = dropped.get("介绍太短", 0) + len(short)
        cands = [c for c in cands if c not in short]
    print(f"[过滤] 送去打分 {len(cands)} 个；淘汰：{dropped}")

    ranked = score.score_all(cands, history, today)
    if not ranked:
        raise RuntimeError("没有任何候选完成打分")
    top = score.pick_top(ranked, config.TOP_N)
    for i, t in enumerate(top, 1):
        print(f"  #{i} [{t['kind']}] {t['title'][:60]} 综合 {t['score']['final']} "
              f"[{t['eval'].get('topic')}] {t['eval'].get('one_liner')}")
    pick = top[0]

    try:
        hot = trend.find_trend(ranked, history, today)
    except Exception as err:  # 热门技术只是附加栏目，出错不影响日报
        print(f"[热门技术] 失败：{err}")
        hot = None

    content = generate.write_content(pick, top[1:])
    daily = {"date": ts, "headline": content["headline"], "title_en": content["title_en"],
             "tagline_en": content["tagline_en"], "summary_md": content["summary_md"],
             "pick": public_item(pick), "top": [public_item(t) for t in top],
             "trend": {k: v for k, v in hot.items() if k != "explainer_md"} if hot else None}
    (config.DATA / "daily").mkdir(parents=True, exist_ok=True)
    (config.DATA / "daily" / f"{ts}.json").write_text(json.dumps(daily, ensure_ascii=False, indent=1))

    new_terms = update_glossary(top, ts)
    history["picks"].append({"date": ts, "id": pick["id"], "title": pick["title"],
                             "topic": pick["eval"].get("topic", ""), "final": pick["score"]["final"]})
    cutoff = (today - timedelta(days=30)).isoformat()
    history["top"] = {i: d for i, d in history["top"].items() if d >= cutoff}
    history["top"].update({t["id"]: ts for t in top})
    filters.save_history(history)
    site.build()

    link = f"{config.SITE_URL}/daily/{ts}.html"
    tweet = content["tweet"]
    tweet = tweet.replace("{LINK}", link) if "{LINK}" in tweet else (f"{tweet}\n\n{link}" if tweet else "")
    private = {"tweet": tweet, "thread": content["thread"], "link": link,
               "explainer_md": content["explainer_md"], "new_terms": new_terms,
               "trend_md": hot["explainer_md"] if hot else ""}
    stats = {"sources": "，".join(f"{k} {v}" for k, v in source_stats.items()),
             "filtered": len(cands), "scored": len(ranked),
             "dropped": "，".join(f"{k} {v}" for k, v in dropped.items()) or "无",
             "llm": llm.usage.summary(), "peak": peak_note}
    subject, body = mailer.build_email(daily, private, stats)
    if args.dry_run:
        config.OUT.mkdir(exist_ok=True)
        (config.OUT / f"email-{ts}.html").write_text(body)
        print(f"[邮件] dry-run，未发送，已保存到 out/email-{ts}.html")
    else:
        mailer.send(subject, body)
    print(f"[完成] 精选 {pick['title']}；{llm.usage.summary()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="不发邮件，邮件内容保存到 out/")
    ap.add_argument("--limit", type=int, default=0, help="最多打分多少个（测试用）")
    ap.add_argument("--skip-if-done", action="store_true", help="当天已生成过日报就直接退出")
    args = ap.parse_args()
    try:
        run(args)
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        if not args.dry_run and config.GMAIL_APP_PASSWORD:
            try:
                mailer.send("[具身雷达] ❌ 今日运行失败",
                            f"<p>今天的流程出错了，详细日志见 GitHub Actions。</p><pre>{mailer.e(tb[-3000:])}</pre>")
            except Exception as mail_err:
                print(f"[邮件] 错误通知也发送失败：{mail_err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
