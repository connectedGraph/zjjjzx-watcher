from __future__ import annotations

import argparse
import os
import sys
import time as time_module
import webbrowser
from pathlib import Path
from typing import Any

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from zjjjzx.config import (
    DEFAULT_CONFIG_NAME,
    find_file,
    load_config,
    load_dotenv,
    validate_config,
)
from zjjjzx.core.engine import run_pipeline
from zjjjzx.core.store import Store


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()


def mask_secret(secret: str | None) -> str:
    if not secret:
        return "[red]未设置[/red]"
    if len(secret) <= 8:
        return "[green]已配置 (***)[/green]"
    return f"[green]已配置 ({secret[:4]}...{secret[-4:]})[/green]"


def print_banner() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]zjjjzx-watcher[/bold cyan] [dim]v0.2.0[/dim]\n"
            "[white]自动化家教需求抓取 · 百度地图驾车测距 · LLM 智能语义筛选与评分[/white]",
            border_style="cyan",
        )
    )


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv(args.env)
    config_path = find_file(args.config)
    if not config_path:
        console.print(f"[bold red]错误：[/bold red] 找不到配置文件 {args.config}")
        return 1

    config = load_config(config_path)

    if args.city:
        if "source" in config:
            config["source"]["city"] = args.city
        if "maps" in config:
            config["maps"]["city"] = args.city

    def execute_once() -> int:
        with Status("[bold cyan][阶段 1/3] 正在拉取家教平台最新发布...", console=console) as status:
            candidates_found = 0

            def on_event(event: str, data: dict[str, Any]) -> None:
                nonlocal candidates_found
                if event == "stage_change":
                    status.update(f"[bold cyan]▶ {data.get('message', '')}")
                elif event == "listings_fetched":
                    status.update(f"[bold cyan][阶段 2/3] 已获取 {data['count']} 条，正在计算驾车距离与硬过滤...")
                elif event == "listing_step":
                    listing = data["listing"]
                    idx = data["index"]
                    total = data["total"]
                    title_preview = listing.title[:14] if len(listing.title) > 14 else listing.title
                    status.update(f"[bold cyan][阶段 2/3] 测距与初筛 [{idx}/{total}]: {title_preview}...")
                elif event == "eval_progress":
                    done = data["completed"]
                    total = data["total"]
                    listing = data["listing"]
                    res_icon = "[green]✓通过[/green]" if data["passed"] else "[dim red]✗排除[/dim red]"
                    title_preview = listing.title[:12] if len(listing.title) > 12 else listing.title
                    status.update(
                        f"[bold cyan][阶段 3/3] 并发语义评估 [{done}/{total} | 候选:{candidates_found}]: "
                        f"{res_icon} [{listing.external_id}] {title_preview}"
                    )
                elif event == "candidate_added":
                    candidates_found += 1
                    status.update(f"[bold green]★ 发现匹配候选：{data['listing'].external_id} ({data['points']}分)")
                elif event == "log" and data.get("level") in ("warn", "error"):
                    console.print(f"[yellow]提示：[/yellow] {data['message']}")

            result = run_pipeline(
                config=config,
                dry_run=args.dry_run,
                ignore_schedule=args.force,
                enable_llm=not args.no_llm,
                matcher_mode=getattr(args, "method", "llm"),
                embedding_threshold=getattr(args, "threshold", None),
                concurrency=getattr(args, "concurrency", 5),
                enable_rules=not getattr(args, "no_rules", False),
                on_event=on_event,
            )

        if result.get("outside_schedule"):
            console.print("[yellow]当前时间不在配置的轮询窗口内。使用 --force 忽略时间限制强制运行。[/yellow]")
            return 0

        candidates = result["candidates"]
        new_count = result["new_count"]
        fetched = result["fetched"]
        report_path = result.get("report_path")

        table = Table(
            title=f"匹配候选结果 (抓取: {fetched} | 新增: {new_count} | 候选: {len(candidates)})",
            box=ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("#", style="dim", width=4)
        table.add_column("编号", style="bold cyan", width=12)
        table.add_column("评分", style="bold green", justify="right", width=6)
        table.add_column("标题 / 科目", style="white", min_width=20)
        table.add_column("时薪 (元/h)", style="yellow", justify="right", width=12)
        table.add_column("驾车距离", style="blue", justify="right", width=10)
        table.add_column("时间 / 要求", style="dim", min_width=20)

        for index, item in enumerate(candidates, 1):
            listing = item["listing"]
            extracted = item["extracted"]
            points = item["points"]
            dist_val = item["distance_meters"]
            dist_str = f"{dist_val / 1000:.1f} km" if dist_val is not None else "未知"

            rate_min = extracted.get("hourly_rate_min")
            rate_max = extracted.get("hourly_rate_max")
            if rate_min == rate_max and rate_min is not None:
                rate_str = f"{rate_min:g}"
            elif rate_min or rate_max:
                rate_str = f"{rate_min or '?'}-{rate_max or '?'}"
            else:
                rate_str = listing.price_text or "面议"

            time_str = extracted.get("schedule_text") or listing.teaching_time or "不限"
            title_str = f"{listing.title}\n[dim]{listing.address}[/dim]"

            table.add_row(
                str(index),
                listing.external_id,
                f"{points:g}",
                title_str,
                rate_str,
                dist_str,
                time_str,
            )

        console.print(table)
        if report_path:
            console.print(f"[bold green]✓[/bold green] 筛选报告已生成：[underline cyan]{report_path}[/underline cyan]")

        if args.open_report and report_path:
            webbrowser.open(Path(report_path).resolve().as_uri())

        return 0

    if args.loop:
        interval = (args.interval or config.get("schedule", {}).get("interval_hours", 2)) * 3600
        console.print(f"[cyan]已启用定时循环模式，每隔 {interval / 3600:.1f} 小时执行一次 (Ctrl+C 退出)...[/cyan]")
        try:
            while True:
                execute_once()
                time_module.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[yellow]已停止循环。[/yellow]")
            return 0

    return execute_once()


def cmd_candidates(args: argparse.Namespace) -> int:
    load_dotenv()
    config = load_config()
    db_path = config.get("storage", {}).get("database", "data/watcher.db")
    store = Store(db_path)
    try:
        candidates = store.get_candidates(limit=args.limit)
        if not candidates:
            console.print("[yellow]数据库中暂无合格候选数据。[/yellow]")
            return 0

        table = Table(
            title=f"数据库历史匹配候选 ({len(candidates)} 条)",
            box=ROUNDED,
            header_style="bold magenta",
        )
        table.add_column("编号", style="bold cyan", width=12)
        table.add_column("评分", style="bold green", justify="right", width=6)
        table.add_column("科目 / 年级", style="white")
        table.add_column("时薪 (元/h)", style="yellow", justify="right")
        table.add_column("距离", style="blue", justify="right")
        table.add_column("状态", style="magenta")
        table.add_column("理由 / 建议", style="dim", min_width=30)

        for item in candidates:
            listing = item.get("listing", {})
            extracted = item.get("extracted", {})
            dist_val = item.get("distance_meters")
            dist_str = f"{dist_val / 1000:.1f} km" if dist_val is not None else "未知"

            rate_min = extracted.get("hourly_rate_min")
            rate_max = extracted.get("hourly_rate_max")
            if rate_min == rate_max and rate_min is not None:
                rate_str = f"{rate_min:g}"
            elif rate_min or rate_max:
                rate_str = f"{rate_min or '?'}-{rate_max or '?'}"
            else:
                rate_str = listing.get("price_text", "面议")

            status = "[bold green]已通知[/bold green]" if item.get("notified") else "[cyan]待处理[/cyan]"
            if item.get("user_decision") != "pending":
                status = f"[bold]{item.get('user_decision')}[/bold]"

            table.add_row(
                item["external_id"],
                f"{item.get('score', 0):g}",
                f"{listing.get('grade', '')} {listing.get('subject', '')}",
                rate_str,
                dist_str,
                status,
                item.get("llm_reason", ""),
            )

        console.print(table)
        return 0
    finally:
        store.close()


def cmd_rejected(args: argparse.Namespace) -> int:
    load_dotenv()
    config = load_config()
    db_path = config.get("storage", {}).get("database", "data/watcher.db")
    store = Store(db_path)
    try:
        rejected = store.get_rejected(limit=args.limit)
        if not rejected:
            console.print("[green]暂无被拒绝条目。[/green]")
            return 0

        table = Table(
            title=f"未入选条目记录 ({len(rejected)} 条)",
            box=ROUNDED,
            header_style="bold red",
        )
        table.add_column("编号", style="bold cyan", width=12)
        table.add_column("阶段", style="yellow", width=10)
        table.add_column("标题 / 需求", style="white")
        table.add_column("未通过原因", style="red", min_width=30)
        table.add_column("更新时间", style="dim", width=20)

        for item in rejected:
            listing = item.get("listing", {})
            table.add_row(
                item["external_id"],
                item["stage"],
                listing.get("title", ""),
                item["reason"],
                item["updated_at"][:19].replace("T", " "),
            )

        console.print(table)
        return 0
    finally:
        store.close()


def cmd_stats(args: argparse.Namespace) -> int:
    load_dotenv()
    config = load_config()
    db_path = config.get("storage", {}).get("database", "data/watcher.db")
    store = Store(db_path)
    try:
        stats = store.get_stats()
        table = Table(title="系统数据统计", box=ROUNDED)
        table.add_column("指标", style="bold cyan")
        table.add_column("数值", style="bold green", justify="right")

        table.add_row("总记录条目 (Total Listings)", str(stats["total_listings"]))
        table.add_row("已评估条目 (Evaluations)", str(stats["total_evaluations"]))
        table.add_row("合格候选 (Candidates)", str(stats["candidates"]))
        table.add_row("未入选条目 (Rejected)", str(stats["rejected"]))
        table.add_row("地址测距缓存 (Geocode Cache)", str(stats["cached_addresses"]))
        table.add_row("总运行批次 (Total Runs)", str(stats["total_runs"]))

        console.print(table)
        return 0
    finally:
        store.close()


def cmd_history(args: argparse.Namespace) -> int:
    load_dotenv()
    config = load_config()
    db_path = config.get("storage", {}).get("database", "data/watcher.db")
    store = Store(db_path)
    try:
        runs = store.get_runs(limit=args.limit)
        table = Table(title="历史运行记录", box=ROUNDED)
        table.add_column("Run ID", style="bold cyan", width=8)
        table.add_column("开始时间", style="white", width=20)
        table.add_column("抓取量", justify="right", style="blue")
        table.add_column("新增量", justify="right", style="yellow")
        table.add_column("候选量", justify="right", style="green")
        table.add_column("状态 / 错误", style="magenta")

        for r in runs:
            status = "[green]成功[/green]" if not r.get("error") else f"[red]{r.get('error')}[/red]"
            table.add_row(
                str(r["id"]),
                r["started_at"][:19].replace("T", " "),
                str(r["fetched"]),
                str(r["new_count"]),
                str(r["candidate_count"]),
                status,
            )

        console.print(table)
        return 0
    finally:
        store.close()


def cmd_report(args: argparse.Namespace) -> int:
    load_dotenv()
    config = load_config()
    report_path = Path(config.get("storage", {}).get("report", "data/report.html")).resolve()
    if not report_path.is_file():
        console.print(f"[yellow]报告文件尚未生成：{report_path}[/yellow]")
        console.print("可运行 [cyan]zjjjzx run[/cyan] 生成最新报告。")
        return 1

    console.print(f"报告文件路径：[underline cyan]{report_path}[/underline cyan]")
    if args.open:
        console.print("[green]正在默认浏览器中打开报告...[/green]")
        webbrowser.open(report_path.as_uri())
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    load_dotenv()
    config_file = find_file(DEFAULT_CONFIG_NAME)
    console.print(f"配置文件路径：[bold cyan]{config_file or '未找到'}[/bold cyan]")
    if not config_file:
        return 1

    config = load_config(config_file)
    issues = validate_config(config)

    table = Table(title="当前活跃配置", box=ROUNDED)
    table.add_column("配置项", style="bold cyan")
    table.add_column("当前值", style="white")

    source = config.get("source", {})
    table.add_row("数据源 URL", source.get("url", ""))
    table.add_row("目标城市", source.get("city", ""))

    maps_cfg = config.get("maps", {})
    map_ak_env = maps_cfg.get("api_key_env", "BAIDU_MAP_AK")
    table.add_row("测距原点", maps_cfg.get("origin", "未设置"))
    table.add_row("百度地图 AK", f"{map_ak_env} -> {mask_secret(os.getenv(map_ak_env))}")

    llm_cfg = config.get("llm", {})
    llm_ak_env = llm_cfg.get("api_key_env", "DEEPSEEK_API_KEY")
    table.add_row("LLM 模型", llm_cfg.get("model", "deepseek-v4-flash"))
    table.add_row("LLM API Key", f"{llm_ak_env} -> {mask_secret(os.getenv(llm_ak_env))}")

    profile = config.get("profile", {})
    table.add_row("限定区域", ", ".join(profile.get("areas", [])) or "不限")
    table.add_row("匹配科目", ", ".join(profile.get("subjects", [])) or "不限")
    max_dist = profile.get("max_distance_meters")
    table.add_row("最大驾车距离", f"{max_dist / 1000:.1f} km" if max_dist else "不限")

    console.print(table)

    if issues:
        console.print("\n[bold yellow]配置警告 / 建议：[/bold yellow]")
        for issue in issues:
            console.print(f"  [yellow]•[/yellow] {issue}")
    else:
        console.print("\n[bold green]✓ 所有必要配置与 API 密钥均已就绪。[/bold green]")

    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from zjjjzx.tui import run_tui
    run_tui(config_path=args.config)
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from zjjjzx.web import run_web_server
    run_web_server(host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="zjjjzx",
        description="zjjjzx-watcher: 智能家教需求抓取、测距与语义匹配系统",
    )
    parser.add_argument("--version", action="version", version="zjjjzx 0.2.0")
    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # run
    p_run = subparsers.add_parser("run", help="执行家教抓取与匹配流水线")
    p_run.add_argument("-c", "--config", default=DEFAULT_CONFIG_NAME, help="配置文件路径 (默认: config.json)")
    p_run.add_argument("-e", "--env", default=None, help=".env 路径")
    p_run.add_argument("--dry-run", action="store_true", help="试运行模式，不标记条目为已通知")
    p_run.add_argument("--force", action="store_true", help="忽略定时时间窗口强制执行")
    p_run.add_argument("--loop", action="store_true", help="持续轮询模式")
    p_run.add_argument("--interval", type=float, default=None, help="轮询间隔小时数")
    p_run.add_argument("--no-llm", action="store_true", help="跳过 LLM 语义评估，只进行硬过滤与测距")
    p_run.add_argument("--no-rules", action="store_true", help="跳过本地规则与关键词过滤")
    p_run.add_argument(
        "-m", "--method",
        choices=["llm", "embedding", "hybrid"],
        default="llm",
        help="匹配研判方式: llm (大模型语义匹配), embedding (向量相似度极速初筛), hybrid (向量预筛+大模型复审)",
    )
    p_run.add_argument(
        "-t", "--threshold",
        type=float,
        default=None,
        help="Embedding 匹配阈值 (默认 0.08)",
    )
    p_run.add_argument(
        "-j", "--concurrency",
        type=int,
        default=5,
        help="LLM 并发评估线程数 (默认 5)",
    )
    p_run.add_argument("--city", help="临时覆盖抓取城市名称")
    p_run.add_argument("-o", "--open-report", action="store_true", help="执行完成后自动在浏览器打开 HTML 报告")

    # tui
    p_tui = subparsers.add_parser("tui", help="启动交互式终端界面 (Textual TUI)")
    p_tui.add_argument("-c", "--config", default=DEFAULT_CONFIG_NAME, help="配置文件路径")

    # web
    p_web = subparsers.add_parser("web", help="启动 Web 可视化管理控制台")
    p_web.add_argument("-p", "--port", type=int, default=8765, help="Web 服务器端口 (默认: 8765)")
    p_web.add_argument("--host", default="127.0.0.1", help="绑定主机地址 (默认: 127.0.0.1)")
    p_web.add_argument("--no-open", action="store_true", help="启动时不自动打开浏览器")

    # candidates
    p_cand = subparsers.add_parser("candidates", aliases=["list"], help="列出已匹配的合格候选")
    p_cand.add_argument("-n", "--limit", type=int, default=30, help="显示条数限制")

    # rejected
    p_rej = subparsers.add_parser("rejected", help="列出未通过硬过滤或语义评估的记录")
    p_rej.add_argument("-n", "--limit", type=int, default=30, help="显示条数限制")

    # stats
    subparsers.add_parser("stats", help="查看数据库汇总指标与缓存统计")

    # history
    p_hist = subparsers.add_parser("history", aliases=["runs"], help="查看流水线执行历史")
    p_hist.add_argument("-n", "--limit", type=int, default=20, help="显示条数限制")

    # report
    p_rep = subparsers.add_parser("report", help="查看或在浏览器中打开 HTML 筛选报告")
    p_rep.add_argument("-o", "--open", action="store_true", help="在默认浏览器中打开报告")

    # config
    subparsers.add_parser("config", help="查看并校验当前配置与 API 密钥")

    args = parser.parse_args()

    if not args.subcommand:
        # Default behavior when run without arguments: launch TUI or show help
        # If terminal is interactive, we show help or run
        print_banner()
        parser.print_help()
        return 0

    command_map = {
        "run": cmd_run,
        "tui": cmd_tui,
        "web": cmd_web,
        "candidates": cmd_candidates,
        "list": cmd_candidates,
        "rejected": cmd_rejected,
        "stats": cmd_stats,
        "history": cmd_history,
        "runs": cmd_history,
        "report": cmd_report,
        "config": cmd_config,
    }

    handler = command_map.get(args.subcommand)
    if handler:
        return handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
