# zjjjzx-watcher

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![TUI: Textual](https://img.shields.io/badge/TUI-Textual-green.svg)](https://textual.textualize.io/)
[![CLI: Rich](https://img.shields.io/badge/CLI-Rich-purple.svg)](https://rich.readthedocs.io/)

> **Intelligent Tutor Listings Watcher · Driving Route Matrix · LLM Semantic Matcher (CLI & TUI)**

[中文文档 (Chinese Documentation)](README.md)

---

## 🌟 Highlights

`zjjjzx-watcher` is designed for tutors and university students seeking tutoring jobs. It automates monitoring tutor boards, calculates exact driving distances via Map APIs (Baidu Maps / Amap), evaluates complex requirements with LLMs (DeepSeek / OpenAI compatible models), and presents matching candidates through both modern terminal interfaces (CLI & TUI) and responsive HTML reports.

- ⚡ **Automated Crawling & Incremental Storage**: Built-in HTML card parser and SQLite store with smart deduplication.
- 🔍 **Ultra-Fast Rule & Keyword Pre-Filter**: Instant local filtering powered by dataset heuristics—gender requirements, grade ranges (grades 1-12 mapping), allowed/forbidden subject rules, and high-qualification disqualifiers. Pre-filters 90%+ irrelevant listings in milliseconds.
- 🗺️ **High-Precision Driving Distance Matrix**: Batch geocoding and driving route calculations with persistent local cache.
- 🤖 **Concurrent LLM & Embedding Matching**: Supports multi-threaded LLM evaluations (concurrency 5), ultra-fast vector cosine similarity (Embedding mode), and hybrid two-stage screening.
- 🌐 **Web Management Dashboard**: Zero-dependency built-in web management UI (`zjjjzx web` or `zjjjzx-web`) to configure subjects, grade boundaries, exclusion keywords, and API secrets, with real-time pipeline execution logs.
- 🖥️ **Interactive Terminal UI (TUI)**: Sleek dashboard built on `Textual` featuring live candidate inspection, rejection diagnosis, asynchronous worker runner, and real-time logs.
- 💻 **Feature-Rich CLI**: Built with `Rich`, offering commands like `run`, `web`, `tui`, `candidates`, `rejected`, `history`, `stats`, `config`, and `report`.
- 📊 **Responsive HTML Reports**: Clean standalone report cards displaying all metrics and raw listing text.

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/your-username/zjjjzx-watcher.git
cd zjjjzx-watcher

# Install dependencies
pip install rich textual
# Or install in editable mode:
pip install -e .
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and set your API keys:

```bash
cp .env.example .env
```

```ini
BAIDU_MAP_AK=your_baidu_maps_ak_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 3. Configure Preferences

Copy `config.example.json` to `config.json` and adjust your target area, home location, and natural language conditions:

```bash
cp config.example.json config.json
```

---

## 🌐 Web Management Dashboard

Launch the zero-dependency web dashboard at `http://127.0.0.1:8765`:

```bash
python main.py web
# or using package entrypoints:
zjjjzx web
zjjjzx-web
```

Features:
- **Interactive Configuration**: Toggle allowed subjects (Math, English, Homework, Tutoring, etc.), configure minimum/maximum grade bounds (Grade 1 through 12), exclude demanding keywords (e.g. licensed teachers, IELTS), and safely manage API tokens.
- **Candidate Hub**: View passed candidates with scoring, hourly wage calculations, driving distance, and one-click contact tagging.
- **Rejection Diagnostic Panel**: Inspect why non-matching listings were eliminated.
- **Pipeline Runner**: Trigger scans (LLM concurrency 5, Embedding mode, or Hybrid) with live streaming logs.

---

## 🖥️ Interactive TUI Guide

Launch the Textual TUI with:

```bash
python main.py tui
# or using the package entrypoint:
zjjjzx tui
```

### Keybindings
- <kbd>r</kbd>: Start scan immediately
- <kbd>o</kbd>: Open HTML report in default browser
- <kbd>f</kbd>: Refresh data
- <kbd>q</kbd>: Quit

---

## 💻 CLI Commands

```bash
# Run pipeline once
python main.py run

# Useful options
python main.py run --dry-run             # Dry run mode (don't mark as notified)
python main.py run --no-llm              # Rule-based filter only (skips LLM)
python main.py run --force               # Ignore schedule window restrictions
python main.py run --open-report         # Automatically open generated HTML report
python main.py run --loop --interval 2   # Run in polling loop every 2 hours

# Query matched candidates
python main.py candidates

# Query rejected items
python main.py rejected

# System metrics & cache statistics
python main.py stats

# Run history
python main.py history

# Configuration & secret check
python main.py config
```

---

## 🧪 Running Tests

```bash
python -m unittest discover -s tests
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
