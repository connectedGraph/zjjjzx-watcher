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
- 🗺️ **High-Precision Driving Distance Matrix**: Batch geocoding and driving route calculations with persistent local cache.
- 🤖 **LLM Semantic Evaluation**: Define flexible natural-language criteria (e.g., "Accept elementary to grade 10 math; no junior high competitions; college CET-4 English level only; driving distance under 10 km"). The LLM extracts grade levels, calculates hourly wages, estimates total income, and structures requirements.
- 🖥️ **Interactive Terminal UI (TUI)**: Sleek dashboard built on `Textual` featuring live candidate inspection, rejection diagnosis, asynchronous worker runner, and real-time logs.
- 💻 **Feature-Rich CLI**: Built with `Rich`, offering commands like `run`, `candidates`, `rejected`, `history`, `stats`, `config`, and `report`.
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
