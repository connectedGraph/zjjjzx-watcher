import json
import math
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def evaluate_embedding_sample(listing: dict) -> tuple[float, bool, str]:
    title = listing.get("title", "")
    req = listing.get("requirements", "")
    subject = listing.get("subject", "")
    grade = listing.get("grade", "")
    gender_req = listing.get("gender", "")
    text = f"{title} {subject} {grade} {req}"

    # 1. Negative hard disqualifiers
    disqualifiers = [
        "女教", "女大", "女老", "女性", "只限女", "女老师",
        "专职", "在校老师", "在职老师", "师范", "机构老师",
        "考研", "雅思", "托福", "专八", "竞赛", "奥赛",
    ]
    if gender_req == "女":
        return 0.0, False, "要求女教师（性别不匹配）"
    for d in disqualifiers:
        if d in req or d in title:
            return 0.0, False, f"触发排除关键词: {d}"

    # 2. Forbidden subjects
    forbidden = [
        "语文", "物理", "化学", "生物", "历史", "地理", "政治",
        "科学", "钢琴", "画画", "美术", "编程", "计算机", "书法",
    ]
    for f in forbidden:
        if f in subject or f in title:
            return 0.0, False, f"包含未开放科目: {f}"

    # 3. Dense N-gram cosine similarity against target profile
    target = "小学 初中 高一 数学 小学奥数 英语 英语口语 作业辅导 陪读 陪写作业 课后辅导"
    chars = [c for c in text if not c.isspace()]
    bigrams = ["".join(chars[i:i+2]) for i in range(len(chars)-1)]
    words = re.findall(r"[\u4e00-\u9fa5]{2,4}|[a-zA-Z0-9]+", text)
    t_chars = [c for c in target if not c.isspace()]
    t_bigrams = ["".join(t_chars[i:i+2]) for i in range(len(t_chars)-1)]
    t_words = re.findall(r"[\u4e00-\u9fa5]{2,4}|[a-zA-Z0-9]+", target)

    v1 = Counter(words + bigrams)
    v2 = Counter(t_words + t_bigrams)
    inter = set(v1.keys()) & set(v2.keys())
    denom = math.sqrt(sum(v1[x]**2 for x in v1)) * math.sqrt(sum(v2[x]**2 for x in v2))
    sim = (sum(v1[x] * v2[x] for x in inter) / denom) if denom else 0.0

    # Threshold probe
    threshold = 0.075
    passed = (sim >= threshold)
    reason = f"语义相似度 {sim:.3f} >= {threshold}" if passed else f"语义相似度 {sim:.3f} 低于阈值 {threshold}"
    return sim, passed, reason

db_path = Path(__file__).resolve().parent.parent / "data" / "watcher.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT e.external_id, e.llm_pass, e.llm_reason, l.payload "
    "FROM evaluations e JOIN listings l ON e.external_id = l.external_id "
    "WHERE e.hard_pass = 1"
).fetchall()

pos_matched = 0
neg_rejected = 0
print("--- 样本评估明细 ---")
for r in rows:
    p = json.loads(r["payload"])
    sim, passed, reason = evaluate_embedding_sample(p)
    is_llm_pass = (r["llm_pass"] == 1)
    if is_llm_pass:
        if passed:
            pos_matched += 1
            print(f"[OK] 正确召回: {r['external_id']} ({sim:.4f}) {p.get('title')}")
        else:
            print(f"[FN] 漏检候选: {r['external_id']} ({sim:.4f}) {p.get('title')} | 理由: {reason}")
    else:
        if not passed:
            neg_rejected += 1
        else:
            print(f"[FP] 误召条目: {r['external_id']} ({sim:.4f}) {p.get('title')} | LLM理由: {r['llm_reason'][:35]}")

total_pos = sum(1 for r in rows if r["llm_pass"] == 1)
total_neg = sum(1 for r in rows if r["llm_pass"] == 0)
print("\n--- 整体指标汇总 ---")
print(f"正例召回率 (Recall): {pos_matched}/{total_pos} ({pos_matched/total_pos:.1%})")
print(f"负例拦截率 (Specificity): {neg_rejected}/{total_neg} ({neg_rejected/total_neg:.1%})")
print(f"准确率 (Accuracy): {(pos_matched + neg_rejected)/len(rows):.1%}")
