from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from zjjjzx.core.parser import Listing


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _rate_text(extracted: dict) -> str:
    low = extracted.get("hourly_rate_min")
    high = extracted.get("hourly_rate_max")
    nums = (v for v in (low, high) if isinstance(v, (int, float)))
    values = list(nums)
    if not values:
        return "未提取"
    low = values[0] if isinstance(low, (int, float)) else values[-1]
    high = high if isinstance(high, (int, float)) else low
    if low == high:
        return f"{low:g} 元/时"
    return f"{low:g} – {high:g} 元/时"


def _income_text(extracted: dict) -> str:
    value = extracted.get("total_income")
    if isinstance(value, (int, float)):
        return f"{value:g} 元"
    return ""


def _distance_text(distance_meters: float | None) -> str:
    if distance_meters is None:
        return "未测得"
    return f"{distance_meters / 1000:.2f} 公里"


def _distance_class(distance_meters: float | None) -> str:
    if distance_meters is None:
        return ""
    if distance_meters <= 5000:
        return "good"
    if distance_meters <= 8000:
        return "warn"
    return "far"


def _candidate_card(index: int, item: dict) -> str:
    listing: Listing = item["listing"]
    extracted: dict = item["extracted"]
    points: float = item["points"]
    distance: float | None = item["distance_meters"]
    schedule = extracted.get("schedule_text") or listing.teaching_time
    grade = extracted.get("grade") or listing.grade
    mode = extracted.get("mode") or listing.teaching_mode
    gender = extracted.get("student_gender") or listing.gender
    tags = [t for t in (extracted.get("subject") or listing.subject, grade, mode, gender) if t]
    tag_html = "".join(f'<span class="tag">{_esc(t)}</span>' for t in tags)

    income = _income_text(extracted)
    income_html = (
        f'<div class="metric"><span class="k">预计总收入</span>'
        f'<span class="v">{_esc(income)}</span></div>'
        if income
        else ""
    )
    reason_html = f'<p class="reason">{_esc(item["reason"])}</p>' if item["reason"] else ""
    fields = [
        ("编号", listing.external_id),
        ("站点编号", listing.site_job_id),
        ("科目", listing.subject),
        ("年级", listing.grade),
        ("性别要求", listing.gender),
        ("授课方式", listing.teaching_mode),
        ("上课时间", listing.teaching_time),
        ("价格原文", listing.price_text),
        ("区域地址", listing.address),
        ("发布时间", listing.publish_date),
        ("要求", listing.requirements),
    ]
    rows = "".join(
        f"<dt>{_esc(key)}</dt><dd>{_esc(value)}</dd>" for key, value in fields if value
    )
    detail_link = (
        f'<dt>详情页</dt><dd><a href="{_esc(listing.detail_url)}" target="_blank" rel="noopener">'
        f'{_esc(listing.detail_url)}</a></dd>'
        if listing.detail_url
        else ""
    )
    return f"""
<article class="card">
  <div class="card-top">
    <span class="rank">#{index}</span>
    <h2>{_esc(listing.title)}</h2>
    <div class="score"><span class="num">{points:g}</span><span class="label">综合评分</span></div>
  </div>
  <div class="tags">{tag_html}</div>
  <div class="metrics">
    <div class="metric"><span class="k">时薪</span><span class="v">{_esc(_rate_text(extracted))}</span></div>
    {income_html}
    <div class="metric"><span class="k">驾车距离</span><span class="v dist {_distance_class(distance)}">{_esc(_distance_text(distance))}</span></div>
    <div class="metric wide"><span class="k">时间</span><span class="v">{_esc(schedule)}</span></div>
  </div>
  {reason_html}
  <details class="orig">
    <summary>原始详情（全部字段与原文全文）</summary>
    <dl class="fields">{rows}{detail_link}</dl>
    <div class="raw-label">抓取原文</div>
    <blockquote class="raw">{_esc(listing.raw_text)}</blockquote>
  </details>
</article>"""


def write_report(
    path: Path,
    *,
    source_url: str,
    origin: str | None,
    max_distance_meters: float | None,
    fetched: int,
    new_count: int,
    candidates: list[dict],
    rejected: list[dict],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    limit_text = (
        f"{max_distance_meters / 1000:.0f} 公里"
        if max_distance_meters is not None
        else "未限制"
    )
    origin_text = origin or "未设置"

    cards = "".join(
        _candidate_card(index, item) for index, item in enumerate(candidates, 1)
    )

    rejected_rows = "".join(
        f"""<div class="rej-row">
  <span class="rej-title">{_esc(item['listing'].title)}</span>
  <span class="rej-reason">{_esc(item['stage'])} · {_esc(item['reason'])}</span>
  <span class="rej-dist">{_esc(_distance_text(item['distance_meters']))}</span>
</div>"""
        for item in rejected
    )
    rejected_section = (
        f"""
<details class="rejected">
  <summary>本次未入选 {len(rejected)} 条（点击展开原因）</summary>
  {rejected_rows}
</details>"""
        if rejected
        else ""
    )

    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>家教信息筛选报告 · {generated_at}</title>
<style>
:root {{
  --bg:#f5f6f8; --card:#ffffff; --ink:#1a2233; --muted:#69707d;
  --line:#e7eaf0; --accent:#2f54eb; --accent-soft:#eef2ff;
}}
* {{ box-sizing:border-box }}
body {{
  margin:0; background:var(--bg); color:var(--ink); line-height:1.65;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:880px; margin:0 auto; padding:44px 20px 64px }}
.hero h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:.5px }}
.sub {{ color:var(--muted); margin:0 0 24px; font-size:14px }}
.stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:10px }}
.stat {{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 22px; min-width:108px;
}}
.stat .num {{ display:block; font-size:24px; font-weight:700 }}
.stat .label {{ font-size:12px; color:var(--muted) }}
.stat.accent .num {{ color:var(--accent) }}
.meta {{ font-size:12px; color:var(--muted) }}
.card {{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:20px 22px; margin-top:16px; box-shadow:0 1px 2px rgba(16,24,40,.04);
}}
.card-top {{ display:flex; align-items:center; gap:12px }}
.card-top h2 {{ font-size:17px; margin:0; font-weight:600; flex:1; min-width:0 }}
.rank {{
  font-size:13px; font-weight:700; color:var(--accent);
  background:var(--accent-soft); border-radius:8px; padding:2px 10px; white-space:nowrap;
}}
.score {{ text-align:right; white-space:nowrap }}
.score .num {{ font-size:22px; font-weight:700; color:var(--accent); margin-right:6px }}
.score .label {{ font-size:11px; color:var(--muted) }}
.tags {{ margin-top:10px; display:flex; flex-wrap:wrap; gap:6px }}
.tag {{
  font-size:12px; color:#3f4756; background:#f1f3f7; border-radius:999px; padding:2px 10px;
}}
.metrics {{
  display:flex; flex-wrap:wrap; gap:10px 28px; margin-top:14px;
  padding:12px 0; border-top:1px dashed var(--line); border-bottom:1px dashed var(--line);
}}
.metric.wide {{ flex-basis:100% }}
.metric .k {{ font-size:12px; color:var(--muted); margin-right:8px }}
.metric .v {{ font-size:15px; font-weight:600 }}
.v.dist.good {{ color:#0e9f6e }}
.v.dist.warn {{ color:#d97706 }}
.v.dist.far {{ color:#b42318 }}
.reason {{
  margin:12px 0 0; font-size:13.5px; color:#454d5c; background:#f8f9fb;
  border-left:3px solid var(--accent); padding:8px 12px; border-radius:0 8px 8px 0;
}}
details.orig {{ margin-top:12px }}
summary {{
  cursor:pointer; font-size:13px; color:var(--accent); user-select:none;
}}
dl.fields {{
  display:grid; grid-template-columns:auto 1fr; gap:6px 16px;
  margin:12px 0; font-size:13.5px;
}}
dl.fields dt {{ color:var(--muted); white-space:nowrap }}
dl.fields dd {{ margin:0; word-break:break-all }}
dl.fields a {{ color:var(--accent); text-decoration:none }}
dl.fields a:hover {{ text-decoration:underline }}
.raw-label {{ font-size:12px; color:var(--muted); margin-top:4px }}
.raw {{
  margin:6px 0 0; background:#f7f8fa; border:1px solid var(--line); border-radius:8px;
  padding:10px 12px; font-size:13px; color:#4b5563;
  white-space:pre-wrap; word-break:break-word;
}}
.rejected {{
  margin-top:28px; background:var(--card); border:1px solid var(--line);
  border-radius:14px; padding:14px 20px;
}}
.rejected summary {{ color:var(--muted) }}
.rej-row {{
  display:flex; gap:10px; padding:8px 0; border-top:1px solid var(--line);
  font-size:13.5px; align-items:baseline;
}}
.rej-row:first-of-type {{ border-top:none }}
.rej-title {{ font-weight:600; flex:1; min-width:0 }}
.rej-reason {{
  color:#b42318; background:#fef3f2; border-radius:999px; padding:1px 10px;
  font-size:12px; white-space:nowrap;
}}
.rej-dist {{ color:var(--muted); font-size:12px; white-space:nowrap }}
footer.end {{ margin-top:32px; font-size:12px; color:var(--muted); text-align:center }}
@media (max-width:640px) {{
  .rej-row {{ flex-wrap:wrap }}
  dl.fields {{ grid-template-columns:auto 1fr }}
}}
</style>
</head>
<body>
<main class="wrap">
  <header class="hero">
    <h1>家教信息筛选报告</h1>
    <p class="sub">宁波 · 起点「{_esc(origin_text)}」· 驾车距离上限 {_esc(limit_text)}</p>
    <div class="stats">
      <div class="stat"><span class="num">{fetched}</span><span class="label">本次抓取</span></div>
      <div class="stat"><span class="num">{new_count}</span><span class="label">新增条目</span></div>
      <div class="stat accent"><span class="num">{len(candidates)}</span><span class="label">合格候选</span></div>
    </div>
    <p class="meta">生成于 {generated_at} · 候选按综合评分排序 · 数据源 <a href="{_esc(source_url)}" target="_blank" rel="noopener">zjjjzx.com</a></p>
  </header>
  <section>{cards}</section>
  {rejected_section}
  <footer class="end">本文件由 zjjjzx-watcher 自动生成，请勿直接回复平台；联系前先电话确认课时与价格。</footer>
</main>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")
    return path
