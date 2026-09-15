from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from zjjjzx.config import (
    DEFAULT_CONFIG_NAME,
    find_file,
    load_config,
    load_dotenv,
    validate_config,
)
from zjjjzx.core.engine import run_pipeline
from zjjjzx.core.store import Store


TUI_CSS = """
Screen {
    background: #0f141c;
    color: #e2e8f0;
}

Header {
    background: #1a2234;
    color: #38bdf8;
}

Footer {
    background: #1a2234;
    color: #94a3b8;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    padding: 1 2;
}

#candidates-split, #rejected-split {
    height: 1fr;
}

#candidates-table, #rejected-table, #runs-table {
    height: 1fr;
    border: round #334155;
}

#candidate-detail-container, #rejected-detail-container {
    width: 45%;
    height: 1fr;
    border: round #334155;
    padding: 1;
    background: #151d2e;
    margin-left: 1;
}

.detail-title {
    font-size: 16;
    color: #38bdf8;
    text-style: bold;
    margin-bottom: 1;
}

.detail-sub {
    color: #94a3b8;
    margin-bottom: 1;
}

.detail-metric-box {
    background: #1e293b;
    border: round #475569;
    padding: 1;
    margin-bottom: 1;
}

.detail-reason {
    background: #1e293b;
    border-left: wide #38bdf8;
    padding: 1;
    margin-bottom: 1;
    color: #cbd5e1;
}

.detail-raw {
    background: #0f172a;
    border: round #334155;
    padding: 1;
    color: #94a3b8;
    height: auto;
    max-height: 12;
}

.actions-row {
    height: auto;
    margin-top: 1;
    align-horizontal: right;
}

.actions-row Button {
    margin-left: 1;
}

/* Runner Tab */
#runner-controls {
    height: auto;
    padding: 1;
    background: #151d2e;
    border: round #334155;
    margin-bottom: 1;
}

#runner-log {
    height: 1fr;
    border: round #334155;
    background: #090d16;
}

/* Stats Tab */
.stat-card-row {
    height: auto;
    margin-bottom: 1;
}

.stat-card {
    height: auto;
    min-width: 20;
    margin-right: 2;
    padding: 1 2;
    background: #151d2e;
    border: round #38bdf8;
}

.stat-card-num {
    font-size: 24;
    text-style: bold;
    color: #38bdf8;
}

.stat-card-label {
    color: #94a3b8;
}

/* Config Tab */
.config-section {
    background: #151d2e;
    border: round #334155;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
"""


class TutorWatcherApp(App):
    CSS = TUI_CSS
    TITLE = "zjjjzx 智能家教监控终端"
    SUB_TITLE = "TUI Dashboard v0.2.0"

    BINDINGS = [
        Binding("q", "quit", "退出", show=True),
        Binding("r", "run_scan", "立即抓取", show=True),
        Binding("o", "open_report", "打开报告", show=True),
        Binding("f", "refresh_data", "刷新", show=True),
    ]

    def __init__(self, config_path: str = DEFAULT_CONFIG_NAME, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.config_path_arg = config_path
        self.config: dict[str, Any] = {}
        self.store: Store | None = None
        self.current_candidates: list[dict[str, Any]] = []
        self.current_rejected: list[dict[str, Any]] = []
        self.selected_candidate_idx = 0
        self.selected_rejected_idx = 0
        self.is_scanning = False

    def on_mount(self) -> None:
        load_dotenv()
        cfg_file = find_file(self.config_path_arg)
        if cfg_file:
            self.config = load_config(cfg_file)
        else:
            self.config = load_config()

        db_path = self.config.get("storage", {}).get("database", "data/watcher.db")
        self.store = Store(db_path)

        self.setup_tables()
        self.refresh_all_data()

    def setup_tables(self) -> None:
        # Candidates table
        cand_table = self.query_one("#candidates-table", DataTable)
        cand_table.cursor_type = "row"
        cand_table.add_columns(
            "#", "编号", "评分", "标题 / 科目", "时薪", "距离", "方式", "状态"
        )

        # Rejected table
        rej_table = self.query_one("#rejected-table", DataTable)
        rej_table.cursor_type = "row"
        rej_table.add_columns("编号", "阶段", "标题", "原因", "测距")

        # Runs table
        runs_table = self.query_one("#runs-table", DataTable)
        runs_table.cursor_type = "row"
        runs_table.add_columns("ID", "开始时间", "抓取量", "新增量", "合格量", "状态")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-candidates"):
            with TabPane("匹配候选", id="tab-candidates"):
                with Horizontal(id="candidates-split"):
                    yield DataTable(id="candidates-table")
                    with ScrollableContainer(id="candidate-detail-container"):
                        yield Static(id="candidate-detail-content")
                        with Horizontal(classes="actions-row"):
                            yield Button("在浏览器打开", id="btn-open-url", variant="primary")
                            yield Button("标记为已联系", id="btn-mark-contacted", variant="success")

            with TabPane("未入选记录", id="tab-rejected"):
                with Horizontal(id="rejected-split"):
                    yield DataTable(id="rejected-table")
                    with ScrollableContainer(id="rejected-detail-container"):
                        yield Static(id="rejected-detail-content")

            with TabPane("任务控制与日志", id="tab-runner"):
                with Horizontal(id="runner-controls"):
                    yield Button("开始抓取与评估", id="btn-start-scan", variant="success")
                    yield Checkbox("试运行 (Dry Run)", id="chk-dry-run", value=False)
                    yield Checkbox("跳过 LLM 语义评估", id="chk-no-llm", value=False)
                    yield Checkbox("强制忽略时间窗口", id="chk-force-schedule", value=True)
                yield RichLog(id="runner-log", highlight=True, markup=True)

            with TabPane("历史与统计", id="tab-history"):
                with Horizontal(classes="stat-card-row"):
                    with Vertical(classes="stat-card"):
                        yield Label("0", id="stat-total-listings", classes="stat-card-num")
                        yield Label("总记录家教", classes="stat-card-label")
                    with Vertical(classes="stat-card"):
                        yield Label("0", id="stat-candidates", classes="stat-card-num")
                        yield Label("合格候选", classes="stat-card-label")
                    with Vertical(classes="stat-card"):
                        yield Label("0", id="stat-rejected", classes="stat-card-num")
                        yield Label("未入选", classes="stat-card-label")
                    with Vertical(classes="stat-card"):
                        yield Label("0", id="stat-cached-addr", classes="stat-card-num")
                        yield Label("测距缓存", classes="stat-card-label")
                yield DataTable(id="runs-table")

            with TabPane("偏好配置", id="tab-config"):
                with ScrollableContainer():
                    yield Static(id="config-summary-view")

        yield Footer()

    def refresh_all_data(self) -> None:
        if not self.store:
            return

        # 1. Refresh candidates
        self.current_candidates = self.store.get_candidates()
        cand_table = self.query_one("#candidates-table", DataTable)
        cand_table.clear()
        for idx, item in enumerate(self.current_candidates, 1):
            listing = item.get("listing", {})
            extracted = item.get("extracted", {})
            dist_val = item.get("distance_meters")
            dist_str = f"{dist_val / 1000:.1f}km" if dist_val is not None else "未知"

            rate_min = extracted.get("hourly_rate_min")
            rate_max = extracted.get("hourly_rate_max")
            if rate_min == rate_max and rate_min is not None:
                rate_str = f"{rate_min:g}"
            elif rate_min or rate_max:
                rate_str = f"{rate_min or '?'}-{rate_max or '?'}"
            else:
                rate_str = listing.get("price_text", "面议")

            status = "已通知" if item.get("notified") else "待处理"
            cand_table.add_row(
                str(idx),
                item.get("external_id", ""),
                f"{item.get('score', 0):g}",
                listing.get("title", ""),
                rate_str,
                dist_str,
                listing.get("teaching_mode", ""),
                status,
                key=str(idx - 1),
            )

        if self.current_candidates:
            self.show_candidate_detail(0)
        else:
            self.query_one("#candidate-detail-content", Static).update(
                "[yellow]暂无匹配的候选家教记录。可在「任务控制」标签中发起抓取。[/yellow]"
            )

        # 2. Refresh rejected
        self.current_rejected = self.store.get_rejected(limit=100)
        rej_table = self.query_one("#rejected-table", DataTable)
        rej_table.clear()
        for idx, item in enumerate(self.current_rejected):
            listing = item.get("listing", {})
            dist_val = item.get("distance_meters")
            dist_str = f"{dist_val / 1000:.1f}km" if dist_val is not None else "未知"
            rej_table.add_row(
                item.get("external_id", ""),
                item.get("stage", ""),
                listing.get("title", ""),
                item.get("reason", ""),
                dist_str,
                key=str(idx),
            )

        if self.current_rejected:
            self.show_rejected_detail(0)
        else:
            self.query_one("#rejected-detail-content", Static).update("[green]暂无未入选记录。[/green]")

        # 3. Refresh Stats
        stats = self.store.get_stats()
        self.query_one("#stat-total-listings", Label).update(str(stats["total_listings"]))
        self.query_one("#stat-candidates", Label).update(str(stats["candidates"]))
        self.query_one("#stat-rejected", Label).update(str(stats["rejected"]))
        self.query_one("#stat-cached-addr", Label).update(str(stats["cached_addresses"]))

        # 4. Refresh Runs
        runs_table = self.query_one("#runs-table", DataTable)
        runs_table.clear()
        runs = self.store.get_runs(limit=30)
        for r in runs:
            status_text = "成功" if not r.get("error") else f"异常: {r.get('error')}"
            runs_table.add_row(
                str(r["id"]),
                r["started_at"][:19].replace("T", " "),
                str(r["fetched"]),
                str(r["new_count"]),
                str(r["candidate_count"]),
                status_text,
            )

        # 5. Refresh Config summary
        self.update_config_view()

    def show_candidate_detail(self, index: int) -> None:
        if index < 0 or index >= len(self.current_candidates):
            return
        self.selected_candidate_idx = index
        item = self.current_candidates[index]
        listing = item.get("listing", {})
        extracted = item.get("extracted", {})
        dist_val = item.get("distance_meters")
        dist_str = f"{dist_val / 1000:.2f} 公里" if dist_val is not None else "未知"

        rate_min = extracted.get("hourly_rate_min")
        rate_max = extracted.get("hourly_rate_max")
        rate_str = (
            f"{rate_min} 元/时"
            if rate_min == rate_max and rate_min is not None
            else f"{rate_min or '?'}-{rate_max or '?'} 元/时"
        )
        income_str = f"{extracted.get('total_income')} 元" if extracted.get("total_income") else "无法预估"

        content = f"""[b class="detail-title"]#{index + 1} {listing.get('title', '')}[/b]
[dim class="detail-sub"]编号: {item.get('external_id')} | 发布时间: {listing.get('publish_date')} | 综合评分: [bold green]{item.get('score', 0):g}[/bold green][/dim]

[b]▍核心指标[/b]
  • [cyan]测距距离:[/cyan] [bold]{dist_str}[/bold]
  • [cyan]预估时薪:[/cyan] [bold yellow]{rate_str}[/bold yellow]
  • [cyan]预计总收益:[/cyan] {income_str}
  • [cyan]年级/科目:[/cyan] {listing.get('grade')} · {listing.get('subject')}
  • [cyan]授课方式:[/cyan] {listing.get('teaching_mode')}
  • [cyan]授课时间:[/cyan] {extracted.get('schedule_text') or listing.get('teaching_time')}
  • [cyan]地址区域:[/cyan] {listing.get('address')}

[b]▍LLM 推荐理由[/b]
[div class="detail-reason"]{item.get('llm_reason') or '无评估信息'}[/div]

[b]▍要求与详情[/b]
[dim]{listing.get('requirements') or '无特别要求'}[/dim]

[b]▍抓取原文[/b]
[div class="detail-raw"]{listing.get('raw_text', '')}[/div]
"""
        self.query_one("#candidate-detail-content", Static).update(content)

    def show_rejected_detail(self, index: int) -> None:
        if index < 0 or index >= len(self.current_rejected):
            return
        self.selected_rejected_idx = index
        item = self.current_rejected[index]
        listing = item.get("listing", {})
        dist_val = item.get("distance_meters")
        dist_str = f"{dist_val / 1000:.2f} 公里" if dist_val is not None else "未测得"

        content = f"""[b class="detail-title"]{listing.get('title', '未入选条目')}[/b]
[dim]编号: {item.get('external_id')} | 更新时间: {item.get('updated_at')[:19].replace('T', ' ')}[/dim]

[b]▍未通过阶段[/b]
[bold red]{item.get('stage')}[/bold red]

[b]▍拒绝原因[/b]
[div class="detail-reason"][red]{item.get('reason')}[/red][/div]

[b]▍家教信息快照[/b]
  • 区域地址: {listing.get('address')}
  • 驾车测距: {dist_str}
  • 价格原文: {listing.get('price_text')}
  • 年级科目: {listing.get('grade')} · {listing.get('subject')}
  • 授课方式: {listing.get('teaching_mode')}

[b]▍原始详情[/b]
[div class="detail-raw"]{listing.get('raw_text', '')}[/div]
"""
        self.query_one("#rejected-detail-content", Static).update(content)

    def update_config_view(self) -> None:
        issues = validate_config(self.config)
        maps_cfg = self.config.get("maps", {})
        map_ak_set = bool(os.getenv(maps_cfg.get("api_key_env", "BAIDU_MAP_AK")))
        llm_cfg = self.config.get("llm", {})
        llm_ak_set = bool(os.getenv(llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")))
        profile = self.config.get("profile", {})

        status_text = "[bold green]✓ 所有必要配置正常[/bold green]" if not issues else f"[bold red]发现 {len(issues)} 项警告[/bold red]"

        content = f"""[b class="detail-title"]配置与运行状态[/b]
状态: {status_text}

[b]▍数据源[/b]
  • 目标地址: {self.config.get('source', {}).get('url')}
  • 目标城市: {self.config.get('source', {}).get('city')}

[b]▍地图与距离测算[/b]
  • 百度地图 AK: {"[green]已配置[/green]" if map_ak_set else "[red]未检测到环境变量[/red]"}
  • 测距原点: {maps_cfg.get('origin', '未设置')}
  • 最大限制: {profile.get('max_distance_meters', 10000) / 1000:.1f} 公里

[b]▍LLM 语义模型[/b]
  • 供应商模型: {llm_cfg.get('model', 'deepseek-v4-flash')}
  • API Key: {"[green]已配置[/green]" if llm_ak_set else "[red]未设置[/red]"}

[b]▍匹配偏好设定[/b]
  • 偏好区域: {', '.join(profile.get('areas', [])) or '不限'}
  • 允许科目: {', '.join(profile.get('subjects', [])) or '不限'}
  • 允许线上: {"是" if profile.get('allow_online') else "否"}
  • 用户性别: {profile.get('user_gender') or '未设置'}

[b]▍自然语言条件设定 (Prompt Conditions)[/b]
[div class="detail-reason"]{profile.get('conditions', '未设置')}[/div]
"""
        self.query_one("#config-summary-view", Static).update(content)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "candidates-table":
            if event.row_key and event.row_key.value is not None:
                idx = int(event.row_key.value)
                self.show_candidate_detail(idx)
        elif event.data_table.id == "rejected-table":
            if event.row_key and event.row_key.value is not None:
                idx = int(event.row_key.value)
                self.show_rejected_detail(idx)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-start-scan":
            self.action_run_scan()
        elif button_id == "btn-open-url":
            self.open_current_candidate_url()
        elif button_id == "btn-mark-contacted":
            self.mark_current_candidate_contacted()

    def open_current_candidate_url(self) -> None:
        if not self.current_candidates or self.selected_candidate_idx >= len(self.current_candidates):
            return
        item = self.current_candidates[self.selected_candidate_idx]
        url = item.get("listing", {}).get("detail_url")
        if url:
            webbrowser.open(url)
            self.notify(f"已在浏览器中打开: {url}")
        else:
            self.notify("该条目没有详情页 URL", severity="warning")

    def mark_current_candidate_contacted(self) -> None:
        if not self.store or not self.current_candidates:
            return
        if self.selected_candidate_idx >= len(self.current_candidates):
            return
        item = self.current_candidates[self.selected_candidate_idx]
        ext_id = item["external_id"]
        self.store.mark_notified(ext_id, True)
        self.store.update_user_decision(ext_id, "已联系")
        self.notify(f"已标记 [{ext_id}] 为已联系", severity="information")
        self.refresh_all_data()

    def action_run_scan(self) -> None:
        if self.is_scanning:
            self.notify("当前抓取任务正在执行中，请稍候...", severity="warning")
            return
        self.is_scanning = True
        btn = self.query_one("#btn-start-scan", Button)
        btn.disabled = True
        btn.label = "抓取中..."
        self.notify("开始执行家教抓取与匹配流水线...")

        dry_run = self.query_one("#chk-dry-run", Checkbox).value
        no_llm = self.query_one("#chk-no-llm", Checkbox).value
        force = self.query_one("#chk-force-schedule", Checkbox).value

        self.run_scan_worker(dry_run=dry_run, no_llm=no_llm, force=force)

    @work(thread=True)
    def run_scan_worker(self, dry_run: bool, no_llm: bool, force: bool) -> None:
        runner_log = self.query_one("#runner-log", RichLog)

        def log_ui(msg: str) -> None:
            self.call_from_thread(runner_log.write, msg)

        def on_event(event: str, data: dict[str, Any]) -> None:
            if event == "run_started":
                log_ui(f"[bold cyan]▶ 任务启动[/bold cyan] (Run #{data.get('run_id')}): 请求 {data.get('url')}")
            elif event == "listings_fetched":
                log_ui(f"[bold green]✓ 抓取成功:[/bold green] 获取到 {data.get('count')} 条家教需求")
            elif event == "candidate_added":
                listing = data.get("listing")
                log_ui(
                    f"[bold green]★ 发现候选:[/bold green] [{listing.external_id}] {listing.title} "
                    f"([yellow]{data.get('points')}分[/yellow], 距离: {data.get('distance_meters', 0)/1000:.1f}km)"
                )
            elif event == "rejected_item":
                listing = data.get("listing")
                log_ui(f"[dim]✗ 排除条目: [{listing.external_id}] {data.get('stage')} · {data.get('reason')}[/dim]")
            elif event == "report_generated":
                log_ui(f"[bold magenta]📄 报告已写入:[/bold magenta] {data.get('path')}")
            elif event == "log":
                color = "red" if data.get("level") == "error" else "yellow" if data.get("level") == "warn" else "white"
                log_ui(f"[{color}]{data.get('message')}[/{color}]")

        try:
            res = run_pipeline(
                config=self.config,
                dry_run=dry_run,
                ignore_schedule=force,
                enable_llm=not no_llm,
                on_event=on_event,
            )
            if res.get("outside_schedule"):
                log_ui("[yellow]当前不在配置的时间窗口内。勾选「强制忽略时间窗口」可跳过限制。[/yellow]")
            else:
                log_ui(
                    f"[bold green]任务完成！[/bold green] "
                    f"本次抓取 {res.get('fetched')} 条，新增 {res.get('new_count')} 条，合格候选 {len(res.get('candidates', []))} 条"
                )
        except Exception as err:
            log_ui(f"[bold red]抓取过程发生异常：[/bold red] {err}")
        finally:
            def reset_btn() -> None:
                self.is_scanning = False
                btn = self.query_one("#btn-start-scan", Button)
                btn.disabled = False
                btn.label = "开始抓取与评估"
                self.refresh_all_data()

            self.call_from_thread(reset_btn)

    def action_open_report(self) -> None:
        report_path = Path(self.config.get("storage", {}).get("report", "data/report.html")).resolve()
        if report_path.is_file():
            webbrowser.open(report_path.as_uri())
            self.notify(f"已打开报告：{report_path}")
        else:
            self.notify("报告文件尚未生成，请先执行抓取", severity="warning")

    def action_refresh_data(self) -> None:
        self.refresh_all_data()
        self.notify("数据已刷新")


def run_tui(config_path: str = DEFAULT_CONFIG_NAME) -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    app = TutorWatcherApp(config_path=config_path)
    app.run()


if __name__ == "__main__":
    run_tui()
