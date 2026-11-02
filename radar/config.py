"""全局配置。敏感信息只从环境变量读取（GitHub Actions 里来自 Secrets）。"""
import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
PROMPTS = ROOT / "prompts"
OUT = ROOT / "out"  # 本地调试输出，不进仓库

BJ = timezone(timedelta(hours=8))

# ---- 大模型 ----
# api：直接调用 OpenAI 兼容接口（默认 DeepSeek）；dsh：本地调试时借用 dsh headless
LLM_BACKEND = os.getenv("LLM_BACKEND", "api")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
MODEL_SCORE = os.getenv("MODEL_SCORE", "deepseek-flash")
MODEL_WRITE = os.getenv("MODEL_WRITE", "deepseek-flash")
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "8"))

# DeepSeek 谷时价（美元 / 百万 token），只用于邮件里的成本估算；峰时 ×2
PRICE = {"hit": 0.003, "miss": 0.15, "out": 0.6}
# 峰时：周一到周五 UTC 01:00-04:00、06:00-10:00（北京 09-12 点、14-18 点）
PEAK_HOURS_UTC = [(1, 4), (6, 10)]

# ---- GitHub / 网站 / 邮件 ----
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
SITE_URL = os.getenv("SITE_URL", "https://you615074-png.github.io/embodied-radar").rstrip("/")
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
MAIL_TO = os.getenv("MAIL_TO") or GMAIL_ADDRESS
X_HANDLE = os.getenv("X_HANDLE", "").lstrip("@")  # 公开网站上显示的 X 账号，留空就不显示

# ---- 漏斗参数（每类最多送去打分多少个） ----
MAX_PER_KIND = {"paper": 40, "repo": 25, "dataset": 8, "model": 8}
SCORE_CACHE_DAYS = 7     # 7 天内打过分的直接复用，省钱
TOP_N = 5
TOP_PER_KIND = 2         # Top 5 里同一类型（论文 / 仓库 / 数据集 / 模型）最多 2 个
TOP_PER_TOPIC = 2        # 同一主题（操作 / 人形 / VLA ...）最多 2 个
TOP_REPEAT_DAYS = 7      # 7 天内上过 Top 5 的不再进 Top 5
RECENT_TOPIC_DAYS = 3    # 与最近 3 天精选同主题会被扣分
