from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from zjjjzx.config import find_file, load_config, load_dotenv, validate_config
from zjjjzx.core.engine import run_pipeline
from zjjjzx.core.keyword_filter import KeywordFilter, RuleFilterConfig, PRESETS
from zjjjzx.core.store import Store


# Global background task state
_TASK_LOCK = threading.Lock()
_CURRENT_TASK = {
    "is_running": False,
    "stage": "idle",
    "progress_text": "",
    "logs": [],
    "last_result": None,
}


def mask_secret(secret: str | None) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "***"
    return f"{secret[:4]}...{secret[-4:]}"


def _append_log(msg: str, level: str = "info") -> None:
    with _TASK_LOCK:
        _CURRENT_TASK["logs"].append({
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": msg,
        })
        # Keep last 500 logs
        if len(_CURRENT_TASK["logs"]) > 500:
            _CURRENT_TASK["logs"] = _CURRENT_TASK["logs"][-500:]


class WebAppHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs
        pass

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/":
            self._serve_index()
        elif path == "/api/config":
            self._api_get_config()
        elif path == "/api/presets":
            self._send_json({"presets": PRESETS})
        elif path == "/api/candidates":
            self._api_get_candidates()
        elif path == "/api/rejected":
            self._api_get_rejected()
        elif path == "/api/stats":
            self._api_get_stats()
        elif path == "/api/runs":
            self._api_get_runs()
        elif path == "/api/task/status":
            self._api_get_task_status()
        elif path == "/report":
            self._serve_report()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/config":
            self._api_save_config()
        elif path == "/api/task/run":
            self._api_start_run()
        elif path.startswith("/api/candidates/") and path.endswith("/decision"):
            ext_id = path.split("/")[3]
            self._api_update_decision(ext_id)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            return {}
        raw = self.rfile.read(content_len).decode("utf-8")
        return json.loads(raw)

    def _api_get_config(self) -> None:
        load_dotenv()
        cfg_file = find_file("config.json")
        cfg = load_config(cfg_file) if cfg_file else load_config()

        maps_ak_env = cfg.get("maps", {}).get("api_key_env", "BAIDU_MAP_AK")
        llm_ak_env = cfg.get("llm", {}).get("api_key_env", "DEEPSEEK_API_KEY")

        resp = {
            "config": cfg,
            "secrets": {
                "baidu_map_ak": os.getenv(maps_ak_env, ""),
                "baidu_map_ak_masked": mask_secret(os.getenv(maps_ak_env, "")),
                "deepseek_api_key": os.getenv(llm_ak_env, ""),
                "deepseek_api_key_masked": mask_secret(os.getenv(llm_ak_env, "")),
            },
            "validation_issues": validate_config(cfg),
        }
        self._send_json(resp)

    def _api_save_config(self) -> None:
        try:
            payload = self._read_json_body()
            new_cfg = payload.get("config", {})
            secrets = payload.get("secrets", {})

            # 1. Update config.json
            cfg_file = find_file("config.json")
            if not cfg_file:
                cfg_file = Path("config.json").resolve()

            # Preserve non-editable fields if any
            cfg_file.write_text(json.dumps(new_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2. Update .env if secrets provided
            env_file = find_file(".env") or Path(".env").resolve()
            env_lines = []
            if env_file.is_file():
                env_lines = env_file.read_text(encoding="utf-8").splitlines()

            updated_keys = set()
            new_lines = []
            for line in env_lines:
                if line.startswith("BAIDU_MAP_AK=") and "baidu_map_ak" in secrets and secrets["baidu_map_ak"]:
                    new_lines.append(f"BAIDU_MAP_AK={secrets['baidu_map_ak']}")
                    updated_keys.add("BAIDU_MAP_AK")
                    os.environ["BAIDU_MAP_AK"] = secrets["baidu_map_ak"]
                elif line.startswith("DEEPSEEK_API_KEY=") and "deepseek_api_key" in secrets and secrets["deepseek_api_key"]:
                    new_lines.append(f"DEEPSEEK_API_KEY={secrets['deepseek_api_key']}")
                    updated_keys.add("DEEPSEEK_API_KEY")
                    os.environ["DEEPSEEK_API_KEY"] = secrets["deepseek_api_key"]
                else:
                    new_lines.append(line)

            if "BAIDU_MAP_AK" not in updated_keys and secrets.get("baidu_map_ak"):
                new_lines.append(f"BAIDU_MAP_AK={secrets['baidu_map_ak']}")
                os.environ["BAIDU_MAP_AK"] = secrets["baidu_map_ak"]

            if "DEEPSEEK_API_KEY" not in updated_keys and secrets.get("deepseek_api_key"):
                new_lines.append(f"DEEPSEEK_API_KEY={secrets['deepseek_api_key']}")
                os.environ["DEEPSEEK_API_KEY"] = secrets["deepseek_api_key"]

            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

            self._send_json({"success": True, "message": "配置与密钥保存成功！"})
        except Exception as err:
            self._send_json({"success": False, "error": str(err)}, status=400)

    def _get_store(self) -> Store:
        cfg = load_config()
        db_path = cfg.get("storage", {}).get("database", "data/watcher.db")
        return Store(db_path)

    def _api_get_candidates(self) -> None:
        store = self._get_store()
        try:
            candidates = store.get_candidates(limit=100)
            self._send_json({"candidates": candidates})
        finally:
            store.close()

    def _api_get_rejected(self) -> None:
        store = self._get_store()
        try:
            rejected = store.get_rejected(limit=200)
            self._send_json({"rejected": rejected})
        finally:
            store.close()

    def _api_get_stats(self) -> None:
        store = self._get_store()
        try:
            stats = store.get_stats()
            self._send_json({"stats": stats})
        finally:
            store.close()

    def _api_get_runs(self) -> None:
        store = self._get_store()
        try:
            runs = store.get_runs(limit=50)
            self._send_json({"runs": runs})
        finally:
            store.close()

    def _api_update_decision(self, external_id: str) -> None:
        payload = self._read_json_body()
        decision = payload.get("decision", "contacted")
        store = self._get_store()
        try:
            store.update_user_decision(external_id, decision)
            store.mark_notified(external_id, True)
            self._send_json({"success": True, "external_id": external_id, "decision": decision})
        finally:
            store.close()

    def _api_get_task_status(self) -> None:
        with _TASK_LOCK:
            self._send_json({
                "is_running": _CURRENT_TASK["is_running"],
                "stage": _CURRENT_TASK["stage"],
                "progress_text": _CURRENT_TASK["progress_text"],
                "logs": _CURRENT_TASK["logs"][-60:],
                "last_result": _CURRENT_TASK["last_result"],
            })

    def _api_start_run(self) -> None:
        with _TASK_LOCK:
            if _CURRENT_TASK["is_running"]:
                self._send_json({"success": False, "message": "已有抓取任务正在进行中"}, status=409)
                return
            _CURRENT_TASK["is_running"] = True
            _CURRENT_TASK["stage"] = "starting"
            _CURRENT_TASK["progress_text"] = "正在启动抓取流水线..."
            _CURRENT_TASK["logs"].clear()

        payload = self._read_json_body()
        dry_run = payload.get("dry_run", False)
        force = payload.get("force", True)
        matcher_mode = payload.get("matcher_mode", "llm")
        concurrency = int(payload.get("concurrency", 5))
        threshold = payload.get("threshold", None)

        def worker() -> None:
            load_dotenv()
            cfg = load_config()

            def on_event(event: str, data: dict[str, Any]) -> None:
                with _TASK_LOCK:
                    if event == "stage_change":
                        _CURRENT_TASK["stage"] = data.get("stage", "")
                        _CURRENT_TASK["progress_text"] = data.get("message", "")
                        _append_log(f"▶ {data.get('message')}", "info")
                    elif event == "listings_fetched":
                        _CURRENT_TASK["progress_text"] = f"已获取 {data['count']} 条，正在计算距离..."
                        _append_log(f"✓ 抓取页面成功，共发现 {data['count']} 条家教需求", "info")
                    elif event == "eval_progress":
                        done = data["completed"]
                        total = data["total"]
                        listing = data["listing"]
                        tag = "✓ 通过" if data["passed"] else "✗ 排除"
                        _CURRENT_TASK["progress_text"] = f"并发评估 [{done}/{total}]: {listing.external_id}"
                        _append_log(f"[{done}/{total}] {tag} [{listing.external_id}] {listing.title[:15]}", "info" if data["passed"] else "warn")
                    elif event == "candidate_added":
                        _append_log(f"★ 发现匹配候选: [{data['listing'].external_id}] {data['listing'].title} ({data['points']}分)", "success")
                    elif event == "report_generated":
                        _append_log(f"📄 HTML 报告生成成功: {data['path']}", "info")
                    elif event == "log":
                        _append_log(data.get("message", ""), data.get("level", "info"))

            try:
                res = run_pipeline(
                    config=cfg,
                    dry_run=dry_run,
                    ignore_schedule=force,
                    matcher_mode=matcher_mode,
                    embedding_threshold=threshold,
                    concurrency=concurrency,
                    on_event=on_event,
                )
                with _TASK_LOCK:
                    _CURRENT_TASK["last_result"] = {
                        "fetched": res.get("fetched"),
                        "new_count": res.get("new_count"),
                        "candidates_count": len(res.get("candidates", [])),
                        "report_path": res.get("report_path"),
                    }
                    _append_log(f"🎉 任务完成！共抓取 {res.get('fetched')} 条，新增 {res.get('new_count')} 条，合格候选 {len(res.get('candidates', []))} 条", "success")
            except Exception as err:
                with _TASK_LOCK:
                    _append_log(f"❌ 任务异常终止: {err}", "error")
            finally:
                with _TASK_LOCK:
                    _CURRENT_TASK["is_running"] = False
                    _CURRENT_TASK["stage"] = "done"
                    _CURRENT_TASK["progress_text"] = "执行完成"

        threading.Thread(target=worker, daemon=True).start()
        self._send_json({"success": True, "message": "流水线任务已在后台启动"})

    def _serve_report(self) -> None:
        cfg = load_config()
        report_path = Path(cfg.get("storage", {}).get("report", "data/report.html")).resolve()
        if not report_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Report has not been generated yet.")
            return
        content = report_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_index(self) -> None:
        html = HTML_DASHBOARD.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>zjjjzx 智能家教监控控制台</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #131b2e;
      --card-border: #1e293b;
      --text-main: #e2e8f0;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0ea5e9;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      line-height: 1.5;
    }
    .container { max-width: 1280px; margin: 0 auto; padding: 24px 20px; }
    header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--card-border);
    }
    .brand h1 { font-size: 22px; font-weight: 700; color: #fff; }
    .brand p { font-size: 13px; color: var(--text-muted); }
    .nav-tabs { display: flex; gap: 8px; margin-bottom: 20px; }
    .tab-btn {
      background: #1e293b; color: var(--text-muted); border: none; border-radius: 8px;
      padding: 10px 18px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all .2s;
    }
    .tab-btn.active { background: var(--primary); color: #090d16; }
    .tab-btn:hover:not(.active) { background: #334155; color: #fff; }

    .card {
      background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px;
      padding: 20px; margin-bottom: 20px;
    }
    .card h2 { font-size: 17px; margin-bottom: 14px; color: var(--primary); display: flex; align-items: center; gap: 8px; }

    /* Form controls */
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 16px; }
    .form-group { display: flex; flex-direction: column; gap: 6px; }
    .form-group label { font-size: 13px; font-weight: 600; color: var(--text-muted); }
    .form-control {
      background: #0b1120; border: 1px solid #334155; border-radius: 6px;
      padding: 8px 12px; color: #fff; font-size: 14px; outline: none; transition: border .2s;
    }
    .form-control:focus { border-color: var(--primary); }

    /* Chips */
    .chips-group { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .chip {
      background: #1e293b; border: 1px solid #334155; border-radius: 20px;
      padding: 4px 12px; font-size: 13px; cursor: pointer; user-select: none; transition: all .15s;
    }
    .chip.selected { background: var(--primary); color: #090d16; font-weight: 600; border-color: var(--primary); }
    .chip.forbidden-chip.selected { background: var(--danger); color: #fff; border-color: var(--danger); }

    .btn {
      background: var(--primary); color: #090d16; font-weight: 600; border: none;
      border-radius: 6px; padding: 10px 20px; cursor: pointer; transition: background .15s;
    }
    .btn:hover { background: var(--primary-hover); }
    .btn-success { background: var(--success); color: #fff; }
    .btn-danger { background: var(--danger); color: #fff; }
    .btn-outline { background: transparent; border: 1px solid #475569; color: var(--text-main); }
    .btn-outline:hover { background: #1e293b; }

    /* Table */
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
    th { text-align: left; padding: 10px 12px; background: #0f172a; color: var(--text-muted); border-bottom: 1px solid var(--card-border); }
    td { padding: 10px 12px; border-bottom: 1px solid var(--card-border); vertical-align: middle; }
    tr:hover td { background: #1a233a; }
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
    .badge-good { background: rgba(16, 185, 129, .2); color: var(--success); }
    .badge-warn { background: rgba(245, 158, 11, .2); color: var(--warning); }
    .badge-danger { background: rgba(239, 68, 68, .2); color: var(--danger); }

    /* Log terminal */
    .log-box {
      background: #050811; border: 1px solid #1e293b; border-radius: 8px;
      padding: 12px; height: 320px; overflow-y: auto; font-family: Consolas, monospace; font-size: 12.5px;
    }
    .log-line { margin-bottom: 4px; }
    .log-time { color: var(--text-muted); margin-right: 8px; }
    .log-line.success { color: var(--success); }
    .log-line.warn { color: var(--warning); }
    .log-line.error { color: var(--danger); }

    .toast {
      position: fixed; bottom: 20px; right: 20px; background: #1e293b;
      border: 1px solid var(--primary); padding: 12px 20px; border-radius: 8px;
      color: #fff; box-shadow: 0 4px 12px rgba(0,0,0,.5); opacity: 0; transition: opacity .3s; z-index: 999;
    }
    .toast.show { opacity: 1; }
  </style>
</head>
<body>
<div class="container">
  <header>
    <div class="brand">
      <h1>zjjjzx 智能家教监控后台</h1>
      <p>规则与字符串过滤 · 高德/百度地图驾车测距 · LLM/Embedding 并发语义研判</p>
    </div>
    <div>
      <a href="/report" target="_blank" class="btn btn-outline" style="text-decoration:none; display:inline-block; font-size:13px;">查看 HTML 报告 ↗</a>
    </div>
  </header>

  <div class="nav-tabs">
    <button class="tab-btn active" onclick="switchTab('tab-config')">⚙️ 规则与配置管理</button>
    <button class="tab-btn" onclick="switchTab('tab-candidates')">🎯 匹配候选大厅</button>
    <button class="tab-btn" onclick="switchTab('tab-rejected')">🔍 未入选分析看板</button>
    <button class="tab-btn" onclick="switchTab('tab-runner')">🚀 任务控制台与日志</button>
  </div>

  <!-- TAB 1: Config & Rules -->
  <div id="tab-config" class="tab-content">
    <div class="card" style="border: 1px solid #0284c7; background: #0c192c;">
      <h2 style="color: #38bdf8;">⚡ 快速套用预设身份模板 (Presets)</h2>
      <p style="font-size:13px; color:var(--text-muted); margin-bottom:12px;">无论你是理科生、文科生、大学生全科陪读还是音体美特长，点击下方一键切换专属预设与过滤规则：</p>
      <div style="display:flex; flex-wrap:wrap; gap:8px;" id="preset-buttons"></div>
      <div id="preset-desc" style="font-size:12.5px; color:#93c5fd; margin-top:8px; min-height:18px;"></div>
    </div>

    <div class="card">
      <h2>1. 科目与学科允许范围 (Allowed Subjects)</h2>
      <p style="font-size:13px; color:var(--text-muted); margin-bottom:12px;">命中所选学科的家教条目才会被保留（支持点击勾选或点击 × 移除标签）：</p>
      <div class="chips-group" id="subjects-chips"></div>
      <div style="display:flex; gap:8px; margin-top:12px; align-items:center; flex-wrap:wrap;">
        <input type="text" id="new-subject-input" class="form-control" style="width:240px;" placeholder="添加自定义科目 (回车添加)">
        <button class="btn btn-outline" style="padding:6px 14px; font-size:13px;" onclick="addCustomSubject()">+ 添加科目</button>
        <button class="btn btn-outline" style="padding:6px 14px; font-size:13px;" onclick="presetSubjects(['数学', '英语'])">仅数英</button>
        <button class="btn btn-outline" style="padding:6px 14px; font-size:13px;" onclick="presetSubjects(['数学', '英语', '作业辅导', '陪读', '陪写作业', '奥数'])">数英辅导全选</button>
        <button class="btn btn-outline" style="padding:6px 14px; font-size:13px; margin-left:auto;" onclick="allowAllSubjects()">全学科放行 (*)</button>
      </div>
    </div>

    <div class="card">
      <h2>2. 年级段范围与特殊年级规则 (Grade Range)</h2>
      <div class="form-grid">
        <div class="form-group">
          <label>最低年级 (Min Grade)</label>
          <select id="cfg-min-grade" class="form-control">
            <option value="1">小学 1 年级</option>
            <option value="2">小学 2 年级</option>
            <option value="3">小学 3 年级</option>
            <option value="4">小学 4 年级</option>
            <option value="5">小学 5 年级</option>
            <option value="6">小学 6 年级</option>
            <option value="7">初一 / 7年级</option>
          </select>
        </div>
        <div class="form-group">
          <label>最高年级 (Max Grade)</label>
          <select id="cfg-max-grade" class="form-control">
            <option value="6">小学 6 年级</option>
            <option value="9">初三 / 9年级</option>
            <option value="10" selected>高一 / 10年级</option>
            <option value="11">高二 / 11年级</option>
            <option value="12">高三 / 12年级</option>
          </select>
        </div>
        <div class="form-group">
          <label>特殊年级排除 (例如英语不接初三高三)</label>
          <div style="display:flex; align-items:center; gap:8px; margin-top:6px;">
            <input type="checkbox" id="cfg-excl-english-grad" checked>
            <label for="cfg-excl-english-grad" style="color:#fff;">英语自动排除初三与高三 (9/12)</label>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>3. 性别要求、排除限定词与黑名单</h2>
      <div class="form-grid">
        <div class="form-group">
          <label>家教老师性别 (User Gender)</label>
          <select id="cfg-user-gender" class="form-control">
            <option value="男">男性家教 (将自动拦截指定女老师/女大学生的单)</option>
            <option value="女">女性家教 (将自动拦截指定男老师的单)</option>
            <option value="">不限 (不作性别过滤)</option>
          </select>
        </div>
        <div class="form-group">
          <label>允许线上授课 (Allow Online)</label>
          <select id="cfg-allow-online" class="form-control">
            <option value="false">否 (只接线下上门家教)</option>
            <option value="true">是 (接受线上腾讯会议/网课)</option>
          </select>
        </div>
      </div>

      <div class="form-group" style="margin-top:10px;">
        <label>排除限定关键词 (若需求中包含则直接一票否决，逗号分隔)：</label>
        <input type="text" id="cfg-exclude-keywords" class="form-control" style="width:100%;"
               value="专职在校老师, 在校老师, 在职老师, 师范类, 师范专业, 机构老师, 专四, 专八, 雅思, 托福, 初中竞赛, 高中奥赛, 考研">
      </div>

      <div class="form-group" style="margin-top:10px;">
        <label>未开放学科黑名单 (Forbidden Subjects，用逗号分隔，留空则不拦截)：</label>
        <input type="text" id="cfg-forbidden-subjects" class="form-control" style="width:100%;"
               value="语文, 物理, 化学, 生物, 科学, 社会, 历史, 地理, 政治, 体育, 羽毛球, 游泳, 画画, 美术, 书法, 钢琴, 乐器, 编程, 托管班">
      </div>
    </div>

    <div class="card">
      <h2>4. 出行起点与驾车测距 (Baidu Maps)</h2>
      <div class="form-grid">
        <div class="form-group">
          <label>测距原点地址 (Origin)</label>
          <input type="text" id="cfg-maps-origin" class="form-control" placeholder="例如：宁波市鄞州区浙江万里学院">
        </div>
        <div class="form-group">
          <label>最大允许驾车距离 (公里)</label>
          <input type="number" id="cfg-max-distance" class="form-control" value="10" min="1" max="100">
        </div>
        <div class="form-group">
          <label>目标城市 (City)</label>
          <input type="text" id="cfg-city" class="form-control" value="宁波市">
        </div>
      </div>
      <div class="form-group" style="margin-top:8px;">
        <label>百度地图服务端 AK (BAIDU_MAP_AK)</label>
        <input type="password" id="cfg-baidu-ak" class="form-control" placeholder="填入百度开放平台 AK">
      </div>
    </div>

    <div class="card">
      <h2>5. 大语言模型配置 (DeepSeek / OpenAI Compatible)</h2>
      <div class="form-grid">
        <div class="form-group">
          <label>模型名称 (Model)</label>
          <input type="text" id="cfg-llm-model" class="form-control" value="deepseek-v4-flash">
        </div>
        <div class="form-group">
          <label>API Key (DEEPSEEK_API_KEY)</label>
          <input type="password" id="cfg-deepseek-key" class="form-control" placeholder="填入 API Key">
        </div>
        <div class="form-group">
          <label>自定义 Base URL (留空默认官方)</label>
          <input type="text" id="cfg-llm-url" class="form-control" placeholder="https://api.deepseek.com">
        </div>
      </div>
      <div class="form-group" style="margin-top:8px;">
        <label>自然语言约束条件 (Prompt Conditions)</label>
        <textarea id="cfg-conditions" class="form-control" rows="3"></textarea>
      </div>
    </div>

    <div style="display:flex; justify-content:space-between; align-items:center; margin-top:20px; flex-wrap:wrap; gap:12px;">
      <div style="display:flex; gap:8px;">
        <button class="btn btn-outline" style="font-size:13px; padding:8px 16px;" onclick="exportRules()">📋 复制规则 JSON</button>
        <button class="btn btn-outline" style="font-size:13px; padding:8px 16px;" onclick="importRulesPrompt()">📥 导入规则 JSON</button>
      </div>
      <button class="btn btn-success" style="font-size:15px; padding:12px 32px;" onclick="saveConfig()">💾 保存配置并生效</button>
    </div>
  </div>

  <!-- TAB 2: Candidates -->
  <div id="tab-candidates" class="tab-content" style="display:none;">
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
        <h2>🎯 匹配合格候选家教大厅</h2>
        <button class="btn btn-outline" onclick="loadCandidates()">刷新列表</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>编号</th>
              <th>评分</th>
              <th>标题 / 年级科目</th>
              <th>时薪 / 价格</th>
              <th>驾车距离</th>
              <th>状态</th>
              <th>LLM / 规则推荐理由</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="candidates-tbody">
            <tr><td colspan="8" style="text-align:center; color:var(--text-muted);">正在加载候选数据...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 3: Rejected -->
  <div id="tab-rejected" class="tab-content" style="display:none;">
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
        <h2>🔍 未通过筛选条目分析</h2>
        <button class="btn btn-outline" onclick="loadRejected()">刷新记录</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>编号</th>
              <th>拦截阶段</th>
              <th>标题 / 需求原文</th>
              <th>拦截与拒绝原因</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody id="rejected-tbody">
            <tr><td colspan="5" style="text-align:center; color:var(--text-muted);">正在加载未入选数据...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- TAB 4: Runner -->
  <div id="tab-runner" class="tab-content" style="display:none;">
    <div class="card">
      <h2>🚀 任务执行控制台</h2>
      <div style="display:flex; flex-wrap:wrap; gap:16px; align-items:center; margin-bottom:16px;">
        <button class="btn btn-success" id="btn-run" onclick="triggerRun()">立即开始抓取与评估</button>
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
          <input type="checkbox" id="run-dry-run"> 试运行 (Dry Run)
        </label>
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer;">
          <input type="checkbox" id="run-force" checked> 强制执行 (忽略时间限制)
        </label>
        <div style="display:flex; align-items:center; gap:8px;">
          <label style="font-size:13px; color:var(--text-muted);">匹配引擎:</label>
          <select id="run-matcher" class="form-control" style="padding:4px 8px;">
            <option value="llm">大模型并发评估 (LLM Concurrency 5)</option>
            <option value="embedding">极速向量模式 (Embedding Cosine)</option>
            <option value="hybrid">混合模式 (Embedding预筛+LLM复审)</option>
          </select>
        </div>
      </div>
      <div style="margin-bottom:12px;">
        <span style="font-size:13px; color:var(--text-muted);">当前状态: </span>
        <span id="run-status-text" style="font-weight:600; color:var(--primary);">就绪</span>
      </div>
      <div class="log-box" id="log-container">
        <div class="log-line"><span class="log-time">00:00:00</span> [系统] 任务控制台已就绪，点击上方按钮开始抓取。</div>
      </div>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  let ALL_SUBJECTS = ['数学', '英语', '作业辅导', '陪读', '陪写作业', '奥数', '科学', '物理', '化学', '生物', '语文', '社会', '体育', '美术', '编程'];
  let PRESETS_DATA = {};
  let currentConfig = {};

  function showToast(msg) {
    const t = document.getElementById('toast');
    t.innerText = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
  }

  function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    document.getElementById(tabId).style.display = 'block';
    event.target.classList.add('active');

    if (tabId === 'tab-candidates') loadCandidates();
    if (tabId === 'tab-rejected') loadRejected();
  }

  function renderSubjectChips(allList, selectedList) {
    const chipsEl = document.getElementById('subjects-chips');
    chipsEl.innerHTML = '';
    allList.forEach(subj => {
      const isSel = selectedList.includes(subj) || selectedList.includes('*');
      const chip = document.createElement('div');
      chip.className = `chip ${isSel ? 'selected' : ''}`;
      chip.innerHTML = `<span>${subj}</span><span style="margin-left:6px; opacity:0.6; font-size:12px; cursor:pointer;" onclick="event.stopPropagation(); removeSubject('${subj}')" title="删除该科目">×</span>`;
      chip.onclick = () => chip.classList.toggle('selected');
      chipsEl.appendChild(chip);
    });
  }

  function addCustomSubject() {
    const inp = document.getElementById('new-subject-input');
    const val = inp.value.trim();
    if (!val) return;
    if (!ALL_SUBJECTS.includes(val)) ALL_SUBJECTS.push(val);
    const selected = getSelectedSubjects();
    if (!selected.includes(val)) selected.push(val);
    renderSubjectChips(ALL_SUBJECTS, selected);
    inp.value = '';
    showToast(`已添加科目: 【${val}】`);
  }

  function removeSubject(subj) {
    ALL_SUBJECTS = ALL_SUBJECTS.filter(s => s !== subj);
    const selected = getSelectedSubjects().filter(s => s !== subj);
    renderSubjectChips(ALL_SUBJECTS, selected);
    showToast(`已移除科目: 【${subj}】`);
  }

  function getSelectedSubjects() {
    return Array.from(document.querySelectorAll('#subjects-chips .chip.selected span:first-child')).map(el => el.innerText.trim());
  }

  function allowAllSubjects() {
    renderSubjectChips(ALL_SUBJECTS, ALL_SUBJECTS);
    showToast('已全学科开放！');
  }

  function presetSubjects(list) {
    list.forEach(s => { if (!ALL_SUBJECTS.includes(s)) ALL_SUBJECTS.push(s); });
    renderSubjectChips(ALL_SUBJECTS, list);
    showToast('已选中指定科目组合');
  }

  async function loadPresets() {
    try {
      const res = await fetch('/api/presets');
      const data = await res.json();
      PRESETS_DATA = data.presets || {};
      const container = document.getElementById('preset-buttons');
      container.innerHTML = '';
      Object.entries(PRESETS_DATA).forEach(([key, p]) => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-outline';
        btn.style.cssText = 'font-size:12px; padding:5px 12px;';
        btn.innerText = p.name;
        btn.onclick = () => applyPreset(key);
        container.appendChild(btn);
      });
    } catch (e) {
      console.error('加载预设失败:', e);
    }
  }

  function applyPreset(presetKey) {
    const p = PRESETS_DATA[presetKey];
    if (!p) return;
    document.getElementById('preset-desc').innerText = `【${p.name}】: ${p.description}`;

    p.allowed_subjects.forEach(s => {
      if (!ALL_SUBJECTS.includes(s) && s !== '*') ALL_SUBJECTS.push(s);
    });
    renderSubjectChips(ALL_SUBJECTS, p.allowed_subjects);

    document.getElementById('cfg-min-grade').value = p.min_grade || 1;
    document.getElementById('cfg-max-grade').value = p.max_grade || 10;
    const hasEnglishGrad = p.special_grade_rules?.["英语"]?.exclude_grades?.includes(9);
    document.getElementById('cfg-excl-english-grad').checked = !!hasEnglishGrad;
    document.getElementById('cfg-exclude-keywords').value = (p.exclude_keywords || []).join(', ');
    document.getElementById('cfg-forbidden-subjects').value = (p.forbidden_subjects || []).join(', ');

    showToast(`✓ 已套用预设【${p.name}】，点击保存生效！`);
  }

  function exportRules() {
    const rules = {
      user_gender: document.getElementById('cfg-user-gender').value,
      min_grade: parseInt(document.getElementById('cfg-min-grade').value, 10),
      max_grade: parseInt(document.getElementById('cfg-max-grade').value, 10),
      allowed_subjects: getSelectedSubjects(),
      forbidden_subjects: document.getElementById('cfg-forbidden-subjects').value.split(',').map(s => s.trim()).filter(Boolean),
      exclude_keywords: document.getElementById('cfg-exclude-keywords').value.split(',').map(s => s.trim()).filter(Boolean),
      special_grade_rules: document.getElementById('cfg-excl-english-grad').checked ? { "英语": { "exclude_grades": [9, 12] } } : {},
      allow_online: document.getElementById('cfg-allow-online').value === 'true',
    };
    navigator.clipboard.writeText(JSON.stringify(rules, null, 2));
    showToast('已复制完整规则 JSON 到剪贴板！');
  }

  function importRulesPrompt() {
    const raw = prompt('请粘贴要导入的规则 JSON：');
    if (!raw) return;
    try {
      const rules = JSON.parse(raw);
      if (rules.allowed_subjects) {
        rules.allowed_subjects.forEach(s => { if (!ALL_SUBJECTS.includes(s) && s !== '*') ALL_SUBJECTS.push(s); });
        renderSubjectChips(ALL_SUBJECTS, rules.allowed_subjects);
      }
      if (rules.min_grade) document.getElementById('cfg-min-grade').value = rules.min_grade;
      if (rules.max_grade) document.getElementById('cfg-max-grade').value = rules.max_grade;
      if (rules.user_gender) document.getElementById('cfg-user-gender').value = rules.user_gender;
      if (rules.allow_online !== undefined) document.getElementById('cfg-allow-online').value = rules.allow_online ? 'true' : 'false';
      if (rules.exclude_keywords) document.getElementById('cfg-exclude-keywords').value = rules.exclude_keywords.join(', ');
      if (rules.forbidden_subjects) document.getElementById('cfg-forbidden-subjects').value = rules.forbidden_subjects.join(', ');
      if (rules.special_grade_rules?.["英语"]) document.getElementById('cfg-excl-english-grad').checked = true;
      showToast('✓ 规则导入成功！点击保存按钮写入配置。');
    } catch (e) {
      alert('解析规则 JSON 失败: ' + e.message);
    }
  }

  async function loadConfig() {
    try {
      await loadPresets();
      const res = await fetch('/api/config');
      const data = await res.json();
      currentConfig = data.config;

      // Populate subjects chips
      const allowed = currentConfig.rules?.allowed_subjects || currentConfig.profile?.subjects || ['数学', '英语'];
      allowed.forEach(s => { if (!ALL_SUBJECTS.includes(s) && s !== '*') ALL_SUBJECTS.push(s); });
      renderSubjectChips(ALL_SUBJECTS, allowed);

      // Populate form
      document.getElementById('cfg-min-grade').value = currentConfig.rules?.min_grade || 1;
      document.getElementById('cfg-max-grade').value = currentConfig.rules?.max_grade || 10;
      document.getElementById('cfg-user-gender').value = currentConfig.rules?.user_gender || currentConfig.profile?.user_gender || '男';
      document.getElementById('cfg-allow-online').value = (currentConfig.profile?.allow_online ? 'true' : 'false');
      document.getElementById('cfg-exclude-keywords').value = (currentConfig.rules?.exclude_keywords || []).join(', ');
      document.getElementById('cfg-forbidden-subjects').value = (currentConfig.rules?.forbidden_subjects || []).join(', ');

      const hasEnglishGrad = currentConfig.rules?.special_grade_rules?.["英语"]?.exclude_grades?.includes(9);
      document.getElementById('cfg-excl-english-grad').checked = hasEnglishGrad !== false;

      document.getElementById('cfg-maps-origin').value = currentConfig.maps?.origin || '';
      document.getElementById('cfg-max-distance').value = (currentConfig.profile?.max_distance_meters || 10000) / 1000;
      document.getElementById('cfg-city').value = currentConfig.maps?.city || '宁波市';

      document.getElementById('cfg-llm-model').value = currentConfig.llm?.model || 'deepseek-v4-flash';
      document.getElementById('cfg-llm-url').value = currentConfig.llm?.url || '';
      document.getElementById('cfg-conditions').value = currentConfig.profile?.conditions || '';

      if (data.secrets?.baidu_map_ak) document.getElementById('cfg-baidu-ak').value = data.secrets.baidu_map_ak;
      if (data.secrets?.deepseek_api_key) document.getElementById('cfg-deepseek-key').value = data.secrets.deepseek_api_key;
    } catch (e) {
      showToast('加载配置失败: ' + e.message);
    }
  }

  async function saveConfig() {
    const selectedSubjects = getSelectedSubjects();
    const excludeKw = document.getElementById('cfg-exclude-keywords').value.split(',').map(s => s.trim()).filter(Boolean);
    const forbiddenSubj = document.getElementById('cfg-forbidden-subjects').value.split(',').map(s => s.trim()).filter(Boolean);

    currentConfig.profile = currentConfig.profile || {};
    currentConfig.rules = currentConfig.rules || {};
    currentConfig.maps = currentConfig.maps || {};
    currentConfig.llm = currentConfig.llm || {};

    currentConfig.rules.allowed_subjects = selectedSubjects;
    currentConfig.profile.subjects = selectedSubjects;
    currentConfig.rules.forbidden_subjects = forbiddenSubj;
    currentConfig.rules.min_grade = parseInt(document.getElementById('cfg-min-grade').value, 10);
    currentConfig.rules.max_grade = parseInt(document.getElementById('cfg-max-grade').value, 10);
    currentConfig.rules.user_gender = document.getElementById('cfg-user-gender').value;
    currentConfig.profile.user_gender = document.getElementById('cfg-user-gender').value;
    currentConfig.rules.exclude_keywords = excludeKw;

    const hasEnglishGradExcl = document.getElementById('cfg-excl-english-grad').checked;
    currentConfig.rules.special_grade_rules = hasEnglishGradExcl ? { "英语": { "exclude_grades": [9, 12] } } : {};

    currentConfig.profile.allow_online = (document.getElementById('cfg-allow-online').value === 'true');
    currentConfig.rules.allow_online = currentConfig.profile.allow_online;
    currentConfig.maps.origin = document.getElementById('cfg-maps-origin').value;
    currentConfig.maps.city = document.getElementById('cfg-city').value;
    currentConfig.profile.max_distance_meters = parseFloat(document.getElementById('cfg-max-distance').value) * 1000;
    currentConfig.rules.max_distance_meters = currentConfig.profile.max_distance_meters;

    currentConfig.llm.model = document.getElementById('cfg-llm-model').value;
    currentConfig.llm.url = document.getElementById('cfg-llm-url').value;
    currentConfig.profile.conditions = document.getElementById('cfg-conditions').value;

    const secrets = {
      baidu_map_ak: document.getElementById('cfg-baidu-ak').value,
      deepseek_api_key: document.getElementById('cfg-deepseek-key').value,
    };

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: currentConfig, secrets }),
      });
      const data = await res.json();
      if (data.success) showToast('✓ 配置已成功保存！');
      else showToast('保存失败: ' + data.error);
    } catch (e) {
      showToast('保存出错: ' + e.message);
    }
  }

  async function loadCandidates() {
    const tbody = document.getElementById('candidates-tbody');
    try {
      const res = await fetch('/api/candidates');
      const data = await res.json();
      tbody.innerHTML = '';
      if (!data.candidates || !data.candidates.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-muted);">暂无匹配候选条目</td></tr>';
        return;
      }
      data.candidates.forEach((it, idx) => {
        const l = it.listing || {};
        const ext = it.extracted || {};
        const dist = it.distance_meters ? (it.distance_meters/1000).toFixed(1) + ' km' : '未知';
        const rate = ext.hourly_rate_min ? `${ext.hourly_rate_min} 元/h` : (l.price_text || '面议');
        const statusBadge = it.notified ? '<span class="badge badge-good">已联系</span>' : '<span class="badge badge-warn">待联系</span>';

        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${it.external_id}</strong></td>
          <td><strong style="color:var(--primary);">${it.score || 0}</strong></td>
          <td>${l.title || ''}<br><span style="font-size:12px; color:var(--text-muted);">${l.address || ''}</span></td>
          <td><strong style="color:var(--warning);">${rate}</strong></td>
          <td>${dist}</td>
          <td>${statusBadge}</td>
          <td style="max-width:280px; font-size:12.5px; color:#cbd5e1;">${it.llm_reason || '符合规则'}</td>
          <td>
            <a href="${l.detail_url || 'https://zjjjzx.com/teacher/'}" target="_blank" class="btn btn-outline" style="padding:4px 8px; font-size:12px; text-decoration:none;">打开链接</a>
            <button class="btn btn-outline" style="padding:4px 8px; font-size:12px; margin-top:4px;" onclick="copyLink('${l.detail_url}')">复制</button>
            <button class="btn btn-success" style="padding:4px 8px; font-size:12px; margin-top:4px;" onclick="markContacted('${it.external_id}')">标记已联系</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" style="color:var(--danger);">加载失败: ${e.message}</td></tr>`;
    }
  }

  function copyLink(url) {
    navigator.clipboard.writeText(url || 'https://zjjjzx.com/teacher/');
    showToast('已复制网页链接到剪贴板！');
  }

  async function markContacted(id) {
    try {
      await fetch(`/api/candidates/${id}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: 'contacted' }),
      });
      showToast(`已标记 [${id}] 为已联系！`);
      loadCandidates();
    } catch (e) {
      showToast('标记失败: ' + e.message);
    }
  }

  async function loadRejected() {
    const tbody = document.getElementById('rejected-tbody');
    try {
      const res = await fetch('/api/rejected');
      const data = await res.json();
      tbody.innerHTML = '';
      if (!data.rejected || !data.rejected.length) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">暂无未入选记录</td></tr>';
        return;
      }
      data.rejected.forEach(it => {
        const l = it.listing || {};
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><strong>${it.external_id}</strong></td>
          <td><span class="badge badge-danger">${it.stage}</span></td>
          <td><strong>${l.title || ''}</strong><br><span style="font-size:12px; color:var(--text-muted);">${l.requirements || ''}</span></td>
          <td style="color:#f87171;">${it.reason || ''}</td>
          <td style="font-size:12px; color:var(--text-muted);">${(it.updated_at || '').replace('T', ' ').slice(0, 19)}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger);">加载失败: ${e.message}</td></tr>`;
    }
  }

  let taskPollTimer = null;

  async function triggerRun() {
    const dryRun = document.getElementById('run-dry-run').checked;
    const force = document.getElementById('run-force').checked;
    const matcherMode = document.getElementById('run-matcher').value;

    const btn = document.getElementById('btn-run');
    btn.disabled = true;
    btn.innerText = '执行中...';

    try {
      const res = await fetch('/api/task/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: dryRun, force, matcher_mode: matcherMode }),
      });
      const data = await res.json();
      if (!data.success) {
        showToast(data.message);
        btn.disabled = false;
        btn.innerText = '立即开始抓取与评估';
        return;
      }
      showToast('任务已启动！');
      startPollingTask();
    } catch (e) {
      showToast('启动任务失败: ' + e.message);
      btn.disabled = false;
      btn.innerText = '立即开始抓取与评估';
    }
  }

  function startPollingTask() {
    if (taskPollTimer) clearInterval(taskPollTimer);
    taskPollTimer = setInterval(async () => {
      try {
        const res = await fetch('/api/task/status');
        const data = await res.json();

        document.getElementById('run-status-text').innerText = data.progress_text || (data.is_running ? '执行中' : '就绪');

        const logEl = document.getElementById('log-container');
        logEl.innerHTML = '';
        (data.logs || []).forEach(l => {
          const div = document.createElement('div');
          div.className = `log-line ${l.level || 'info'}`;
          div.innerHTML = `<span class="log-time">${l.time}</span> ${l.message}`;
          logEl.appendChild(div);
        });
        logEl.scrollTop = logEl.scrollHeight;

        if (!data.is_running) {
          clearInterval(taskPollTimer);
          document.getElementById('btn-run').disabled = false;
          document.getElementById('btn-run').innerText = '立即开始抓取与评估';
          showToast('任务执行完成！');
        }
      } catch (e) {}
    }, 1000);
  }

  window.onload = () => {
    loadConfig();
  };
</script>
</body>
</html>
"""


def run_web_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server_address = (host, port)
    server = ThreadingHTTPServer(server_address, WebAppHandler)
    url = f"http://{host}:{port}"
    print(f"[Web Dashboard] 控制面板已启动: {url}")
    print(f"[Web Dashboard] 按 Ctrl+C 停止服务器...")
    if open_browser:
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(url)
            else:
                webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Web Dashboard] 服务器已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_web_server()
