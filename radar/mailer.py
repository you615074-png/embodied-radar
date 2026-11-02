"""组装日报邮件并通过 Gmail SMTP 发送。"""
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config
from .score import KIND_ZH
from .site import e, md

STYLE = ("font-family:-apple-system,'PingFang SC',sans-serif;line-height:1.7;color:#1c1917;"
         "max-width:720px;margin:0 auto")
BOX = "border:1px solid #e7e5e4;border-radius:10px;padding:14px 18px;margin:14px 0"


def tweet_len(tweet: str, link: str) -> int:
    """X 把每个链接都按 23 个字符计。"""
    return len(tweet.replace(link, "x" * 23)) if link else len(tweet)


def build_email(d: dict, private: dict, stats: dict) -> tuple[str, str]:
    p = d["pick"]
    subject = f"[具身雷达] {d['date'][5:]} {d['headline'] or p['title']}"
    top = "".join(
        f'<li><b>[{e(KIND_ZH[t["kind"]])}]</b> <a href="{e(t["url"])}">{e(t["title"])}</a> — {e(t["one_liner"])}'
        f'<br><small>🛠 {e(t["how_to_try"])}<br>综合 {t["final"]} · 重要 {t["significance"]} · '
        f'可玩 {t["playable"]} · 热度 {t["heat"]} · {e(t["reason"])}</small></li>' for t in d["top"])
    terms = "".join(f'<li><b>{e(c["term"])}</b>（{e(c.get("zh"))}）：{e(c.get("explain"))}</li>'
                    for c in private["new_terms"])
    terms = f"<h3>📖 今天的新术语</h3><ul>{terms}</ul>" if terms else ""
    thread = ""
    if private["thread"]:
        items = "".join(f'<li style="margin-bottom:8px;white-space:pre-wrap">{e(t)}'
                        f' <small style="color:#78716c">({len(t)})</small></li>' for t in private["thread"])
        thread = f'<h4>🧵 Thread 草稿</h4><ol style="{BOX};padding-left:36px">{items}</ol>'
    flags = "；".join(p.get("red_flags") or []) or "无"
    body = f"""<div style="{STYLE}">
<h2 style="margin-bottom:4px">🤖 {e(d['headline'] or p['title'])}</h2>
<p style="color:#78716c;margin-top:0">{e(KIND_ZH[p['kind']])} · {e(p['topic'])} ·
<a href="{e(p['url'])}">{e(p['title'])}</a></p>
<p><b>{e(p['one_liner'])}</b><br>🛠 没有硬件怎么玩：{e(p['how_to_try'])}<br>⚠️ 疑问：{e(flags)}</p>
<h3>📝 学习笔记</h3>
<div style="{BOX};background:#fafaf9">{md(private['explainer_md'])}</div>
{terms}
<h3>今日 Top {len(d['top'])}</h3><ol>{top}</ol>
<h3>✍️ X 推文草稿</h3>
<div style="{BOX};white-space:pre-wrap">{e(private['tweet']) or '（今天没有生成推文）'}</div>
<p style="color:#78716c;font-size:13px">约 {tweet_len(private['tweet'], private['link'])}/280 字符（链接按 23 计）</p>
{thread}
<h3>运行情况</h3>
<p style="color:#78716c;font-size:13px">采集：{e(stats['sources'])}<br>
规则过滤后 {stats['filtered']} 个 → 打分 {stats['scored']} 个。淘汰原因：{e(stats['dropped'])}<br>
大模型：{e(stats['llm'])} · {e(stats['peak'])}<br>
<a href="{config.SITE_URL}/">公开网站</a> · <a href="{e(private['link'])}">今天这一页</a></p></div>"""
    return subject, body


def send(subject: str, html_body: str):
    if not (config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD):
        raise RuntimeError("缺少 GMAIL_ADDRESS 或 GMAIL_APP_PASSWORD")
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, f"具身雷达 <{config.GMAIL_ADDRESS}>", config.MAIL_TO
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        s.sendmail(config.GMAIL_ADDRESS, [config.MAIL_TO], msg.as_string())
    print(f"[邮件] 已发送：{subject}")
