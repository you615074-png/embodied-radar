# 🤖 Embodied Radar（具身雷达）

每天从 arXiv、Hugging Face 和 GitHub 里挑一个具身智能（机器人 + AI）的新进展，用大白话讲清楚，并说明**没有机器人、只有一台笔记本**能不能上手。

- 公开网站（英文）：https://you615074-png.github.io/embodied-radar/
- 每日邮件（中文）：精选 + 私人学习笔记 + 新术语 + X 推文和 thread 草稿

## 数据源
| 来源 | 内容 | 热度信号 |
|---|---|---|
| arXiv `cs.RO` | 最近 3 天的机器人论文 | 有没有代码 / 项目页 |
| Hugging Face 每日论文 | 社区推荐的论文（只留具身相关） | 点赞数 |
| Hugging Face Hub | LeRobot 数据集、robotics 模型 | trending 分 |
| GitHub | 具身相关 topic 和关键词的新仓库 + trending | 每日新增 star |

## 流程
采集 → 规则过滤（去掉列表、教程、近期已上榜的）→ DeepSeek 打分（重要性、讲得清、惊喜感、无硬件可玩、开放程度、学习价值 + 热度）→ Top 5（同一类型、同一主题最多 2 个）→ 生成内容 → 更新网站 → 发邮件。

北京时间 08:00-23:00 之间每小时触发一次，第一个落在 DeepSeek 谷时的触发负责生成当天日报，其余自动跳过；峰时一律不调用模型（见 `radar/offpeak.py`）。邮件在太平洋时间早上 7 点前送达。

## 配置
仓库 Settings → Secrets and variables → Actions：

| 名称 | 类型 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | Secret | DeepSeek API key |
| `GMAIL_ADDRESS` | Secret | 发信和收信的 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | Secret | Gmail 应用专用密码 |
| `X_HANDLE` | Variable（可选） | 网站上显示的 X 账号 |

## 本地调试
```bash
uv venv -p 3.12 .venv && uv pip install -p .venv/bin/python -r requirements.txt
LLM_BACKEND=dsh .venv/bin/python -m radar.main --dry-run --limit 10
```
