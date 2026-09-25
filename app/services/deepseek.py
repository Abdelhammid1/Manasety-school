"""DeepSeek API client for AI-driven qbank features.

Keeps the key out of source: reads DEEPSEEK_API_KEY (and optional
DEEPSEEK_MODEL, DEEPSEEK_BASE_URL) from the environment. When the key
is missing every entry point raises `AIDisabled` so the caller can
show the "AI is not configured" UI without a 500.

Six features hang off this module (matching the six items from the
"how we can beat qdrat" list):

  1. generate_similar_questions — few-shot from a template's items
     to produce N more of the same shape.
  2. suggest_blueprint_mix — take a subject + grade + target
     question count and propose an easy/medium/hard/very_hard split
     aligned with Bloom's taxonomy.
  3. review_pending_questions — flag near-duplicates and ambiguous
     phrasings among the school's `pending` review-state rows.
  4. grade_free_form_answer — score a short/essay answer against a
     rubric and return {score, feedback}.
  5. summarize_exam_results — after N students submit, name the
     weakest topics and suggest remediation questions.
  6. rewrite_question — rewrite a single question with a directive
     ("harder", "easier", "add a distractor", …).

All six delegate to `_chat()` which owns the retry + JSON parsing
shape. Every feature returns plain dicts/lists so callers don't have
to import the SDK.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


class AIDisabled(RuntimeError):
    """Raised when a caller asks for AI but no key is configured."""


class AIError(RuntimeError):
    """Raised on any error from the upstream API (bad key, 5xx, timeout)."""


def is_configured() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _cfg():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise AIDisabled(
            "DEEPSEEK_API_KEY is not set. Add it to the environment "
            "(e.g. .env) and restart the app."
        )
    return {
        "key":   key,
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "base":  os.environ.get("DEEPSEEK_BASE_URL",
                                 "https://api.deepseek.com").rstrip("/"),
    }


def _chat(system: str, user: str, *, want_json: bool = True,
          temperature: float = 0.7, max_tokens: int = 2048) -> Any:
    """POST /chat/completions and return either the parsed JSON payload
    (when `want_json=True`) or the raw string content."""
    cfg = _cfg()
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": temperature,
        "max_tokens":  max_tokens,
    }
    if want_json:
        body["response_format"] = {"type": "json_object"}
    try:
        r = requests.post(
            f"{cfg['base']}/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg['key']}",
                "Content-Type":  "application/json",
            },
            data=json.dumps(body),
            timeout=45,
        )
    except requests.RequestException as e:
        raise AIError(f"DeepSeek network error: {e}") from e
    if r.status_code >= 400:
        raise AIError(f"DeepSeek {r.status_code}: {r.text[:400]}")
    try:
        content = r.json()["choices"][0]["message"]["content"]
    except (KeyError, ValueError, IndexError) as e:
        raise AIError(f"Unexpected DeepSeek response shape: {e}") from e
    if not want_json:
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise AIError(f"DeepSeek returned non-JSON payload: {e}\n{content[:400]}") from e


# ────────────────────────────────────────────────────────────────────
# 1) Generate more questions matching a template's shape.
# ────────────────────────────────────────────────────────────────────
def generate_similar_questions(examples: list[dict], count: int = 5,
                               subject: str | None = None,
                               difficulty: str | None = None) -> list[dict]:
    """Given a list of {prompt, kind, choices, difficulty} example
    questions, produce `count` new ones of the same shape. Returns a
    list of dicts ready to feed straight into `BankQuestion`."""
    prompt_examples = json.dumps(examples[:6], ensure_ascii=False, indent=2)
    system = (
        "أنت مصمم اختبارات تعليمية عربية للمرحلة المدرسية. "
        "تنتج أسئلة مطابقة تماماً للشكل المطلوب في JSON. "
        "لا تكرر نص الأمثلة، بل ولّد أسئلة مختلفة من نفس النوع والصعوبة."
    )
    user = (
        f"لدي {len(examples)} أسئلة نموذجية"
        f"{' في مادة ' + subject if subject else ''}"
        f"{' بمستوى صعوبة ' + difficulty if difficulty else ''}.\n"
        f"ولّد {count} أسئلة جديدة من نفس النوع تماماً "
        f"({examples[0].get('kind') if examples else 'mcq'}) "
        "وبنفس مستوى الصعوبة. أعد النتيجة كـ JSON بالشكل التالي:\n"
        "{ \"questions\": [{ \"prompt\": \"…\", \"kind\": \"mcq\", "
        "\"difficulty\": \"medium\", \"points\": 1, "
        "\"choices\": [{\"label\": \"…\", \"is_correct\": true}, …] }, …] }\n\n"
        f"الأمثلة المرجعية:\n{prompt_examples}"
    )
    data = _chat(system, user, want_json=True, temperature=0.85)
    if isinstance(data, dict) and "questions" in data:
        return data["questions"]
    if isinstance(data, list):
        return data
    return []


# ────────────────────────────────────────────────────────────────────
# 6) Rewrite a single question with a directive.
# ────────────────────────────────────────────────────────────────────
def rewrite_question(question: dict, directive: str) -> dict:
    """Given a source question dict + a natural-language directive
    ("اجعله أصعب"، "بسّطه للصف الرابع"، "أضف مشتِّتاً" …), return the
    rewritten question in the same JSON shape."""
    system = (
        "أنت محرر أسئلة تعليمية عربية. أعد صياغة السؤال المعطى وفق التوجيه "
        "مع الحفاظ على نفس النوع (kind) وعدد الخيارات، وأعد النتيجة كـ JSON بالشكل نفسه."
    )
    user = (
        f"التوجيه: {directive}\n\n"
        "السؤال الأصلي (JSON):\n"
        + json.dumps(question, ensure_ascii=False, indent=2)
        + "\n\nأعد النسخة المعدّلة كـ JSON فقط، بدون أي شرح إضافي."
    )
    data = _chat(system, user, want_json=True, temperature=0.65)
    return data


# ────────────────────────────────────────────────────────────────────
# 2) Blueprint mix suggestion.
# ────────────────────────────────────────────────────────────────────
def suggest_blueprint_mix(subject: str, grade: str,
                           total_count: int) -> dict:
    """Return a dict {easy, medium, hard, very_hard} summing to
    total_count, aligned with Bloom's taxonomy for the given grade."""
    system = (
        "أنت مصمم مخططات اختبارات (Blueprint) وفق تصنيف بلوم المعرفي. "
        "تقترح توزيعاً منطقياً لمستويات الصعوبة على أسئلة الاختبار."
    )
    user = (
        f"مادة: {subject}\nصف: {grade}\nإجمالي عدد الأسئلة: {total_count}\n\n"
        "اقترح التوزيع المثالي وأعد النتيجة كـ JSON بالشكل:\n"
        "{ \"easy\": N, \"medium\": N, \"hard\": N, \"very_hard\": N, "
        "\"rationale\": \"سبب مختصر باللغة العربية\" }\n"
        "بحيث يكون مجموع الأربعة يساوي بالضبط "
        f"{total_count}."
    )
    return _chat(system, user, want_json=True, temperature=0.4)


# ────────────────────────────────────────────────────────────────────
# 3) Review pending questions for duplicates + ambiguity.
# ────────────────────────────────────────────────────────────────────
def review_pending_questions(questions: list[dict]) -> list[dict]:
    """Take a list of {id, prompt} pending questions. Return a list of
    findings: [{id, verdict: 'ok'|'duplicate'|'ambiguous'|'no_answer',
    note: '…', suggested_state: 'approved'|'pending'|'duplicate'|'no_answer'}]."""
    system = (
        "أنت مراجع أسئلة تعليمية. تفحص قائمة الأسئلة وتحدد التكرار "
        "الدلالي (وليس النصي فقط) والغموض ونقص الإجابة الصحيحة."
    )
    user = (
        "الأسئلة (JSON):\n"
        + json.dumps(questions, ensure_ascii=False, indent=2)
        + "\n\nأعد قائمة النتائج كـ JSON:\n"
        "{ \"findings\": [{\"id\": N, \"verdict\": \"…\", "
        "\"note\": \"…\", \"suggested_state\": \"…\"}, …] }"
    )
    data = _chat(system, user, want_json=True, temperature=0.2, max_tokens=3000)
    return data.get("findings", []) if isinstance(data, dict) else []


# ────────────────────────────────────────────────────────────────────
# 4) Grade a single free-form (short/essay) answer.
# ────────────────────────────────────────────────────────────────────
def grade_free_form_answer(prompt: str, student_answer: str,
                            max_points: float,
                            rubric=None) -> dict:
    """Return {score, feedback, key_points, criterion_scores?}.

    `rubric` may be a plain string (legacy — the assignment's free-form
    instructions) or a dict shaped as {title, description, criteria: [
    {id, title, description, weight, max_score}, ... ]}. When a
    structured rubric is passed the returned JSON also includes
    `criterion_scores`: [{id, score, note}, ...] so the caller can seed
    a rubric-driven manual review UI."""
    system = (
        "أنت مصحح تربوي عربي. تعطي درجة عادلة على السؤال المقالي/القصير "
        "بناءً على نص إجابة الطالب، وتقدم تغذية راجعة قصيرة باللغة العربية."
    )
    if isinstance(rubric, dict) and rubric.get("criteria"):
        rubric_text = (
            f"المعرِّف: {rubric.get('title') or ''}\n"
            f"وصف: {rubric.get('description') or ''}\n"
            "معايير التقييم (JSON):\n"
            + json.dumps(rubric.get("criteria") or [], ensure_ascii=False,
                         indent=2)
        )
        criterion_hint = (
            "\n\"criterion_scores\": ["
            "{\"id\": <id المعيار>, \"score\": <رقم>, \"note\": \"…\"}, …],"
        )
    else:
        rubric_text = rubric or "—"
        criterion_hint = ""
    user = (
        f"السؤال: {prompt}\nالإجابة المقترحة (rubric):\n{rubric_text}\n"
        f"إجابة الطالب:\n{student_answer}\n"
        f"الدرجة القصوى: {max_points}\n\n"
        "أعد النتيجة كـ JSON:\n"
        "{ \"score\": <رقم>, \"feedback\": \"…\","
        f"{criterion_hint}"
        " \"key_points\": [\"نقطة 1\", …] }"
    )
    return _chat(system, user, want_json=True, temperature=0.2)


# ────────────────────────────────────────────────────────────────────
# 5) Post-exam analysis over N students.
# ────────────────────────────────────────────────────────────────────
def summarize_exam_results(exam_title: str,
                            question_stats: list[dict]) -> dict:
    """`question_stats` = [{prompt, correct_pct, topic}, …].
    Returns {weak_topics: [str], recommendations: str}."""
    system = (
        "أنت محلل تعليمي. تحدد الموضوعات الضعيفة بناءً على نسب النجاح "
        "لكل سؤال، وتقترح خطوات علاجية موجزة."
    )
    user = (
        f"اختبار: {exam_title}\n\n"
        "إحصاءات الأسئلة (JSON):\n"
        + json.dumps(question_stats, ensure_ascii=False, indent=2)
        + "\n\nأعد النتيجة كـ JSON:\n"
        "{ \"weak_topics\": [\"…\", …], "
        "\"recommendations\": \"نص عربي مختصر\" }"
    )
    return _chat(system, user, want_json=True, temperature=0.3)
