import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

db_path = Path(__file__).resolve().parent.parent / "data" / "watcher.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

listings = conn.execute("SELECT payload FROM listings").fetchall()
evals = conn.execute(
    "SELECT e.external_id, e.hard_pass, e.hard_reason, e.llm_pass, e.llm_reason, l.payload "
    "FROM evaluations e JOIN listings l ON e.external_id = l.external_id"
).fetchall()

print(f"总家教条目: {len(listings)}")
print(f"总评估条目: {len(evals)}")

subjects = Counter()
grades = Counter()
genders = Counter()
modes = Counter()
req_phrases = Counter()
reasons_hard = Counter()
reasons_llm = Counter()

# Extract common patterns
for l in listings:
    p = json.loads(l["payload"])
    s = p.get("subject", "").strip()
    if s:
        subjects[s] += 1
    g = p.get("grade", "").strip()
    if g:
        grades[g] += 1
    gen = p.get("gender", "").strip()
    if gen:
        genders[gen] += 1
    m = p.get("teaching_mode", "").strip()
    if m:
        modes[m] += 1
    req = p.get("requirements", "").strip()
    for phrase in [
        "专职", "在校老师", "在职老师", "师范", "机构老师", "考研", "竞赛", "奥数",
        "奥赛", "雅思", "托福", "专四", "专八", "女教", "限女", "女老师", "女大",
        "男教", "男老师", "大学生", "经验丰富", "耐心负责", "长期辅导",
    ]:
        if phrase in req:
            req_phrases[phrase] += 1

print("\n--- 1. 所有科目统计 (Subjects) ---")
for s, c in subjects.most_common(25):
    print(f"  {s:15}: {c} 次")

print("\n--- 2. 所有年级统计 (Grades) ---")
for g, c in grades.most_common(25):
    print(f"  {g:15}: {c} 次")

print("\n--- 3. 性别要求 (Gender Requirement) ---")
for gen, c in genders.most_common():
    print(f"  {gen:15}: {c} 次")

print("\n--- 4. 要求中高频限定关键词 (Requirement Key Phrases) ---")
for phrase, c in req_phrases.most_common():
    print(f"  {phrase:15}: {c} 次")

print("\n--- 5. LLM 未入选的核心原因归类分析 ---")
cat_gender = 0
cat_subject = 0
cat_grade = 0
cat_qualification = 0
cat_other = 0

sample_categorized = []

for e in evals:
    if e["hard_pass"] and e["llm_pass"] == 0:
        reason = e["llm_reason"]
        p = json.loads(e["payload"])
        title = p.get("title", "")
        req = p.get("requirements", "")
        matched_tags = []

        if any(k in reason for k in ["性别", "女", "男"]):
            cat_gender += 1
            matched_tags.append("性别不符")
        if any(k in reason for k in ["语文", "物理", "化学", "生物", "科学", "历史", "未明确允许", "学科", "未允许"]):
            cat_subject += 1
            matched_tags.append("学科未开放")
        if any(k in reason for k in ["年级", "高二", "高三", "高一以上", "超出", "初三英语"]):
            cat_grade += 1
            matched_tags.append("年级段超出")
        if any(k in reason for k in ["专职", "在校老师", "师范", "专八", "雅思", "专业水平"]):
            cat_qualification += 1
            matched_tags.append("教师资质要求过高")
        if not matched_tags:
            cat_other += 1
            matched_tags.append("其他语义原因")

        sample_categorized.append((title, matched_tags, reason))

print(f"  • 性别不符排除: {cat_gender} 条")
print(f"  • 学科未开放排除: {cat_subject} 条")
print(f"  • 年级段超出排除: {cat_grade} 条")
print(f"  • 教师资质要求过高(专职/师范/雅思): {cat_qualification} 条")
print(f"  • 其他原因: {cat_other} 条")

print("\n--- 6. 典型未入选条目样本与特征提取 ---")
for title, tags, reason in sample_categorized[:12]:
    print(f"  [{'/'.join(tags)}] {title}")
    print(f"    -> 理由: {reason[:60]}...")
