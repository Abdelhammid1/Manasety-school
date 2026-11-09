"""Replace the generic placeholder lesson body with subject-appropriate
dummy content, varied by lesson position (intro / explanation / exercises).

Run with:  python -m seeds.update_lesson_content
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from app import create_app
from app.extensions import db
from app.models.lms import Course, Lesson
from app.models.teacher import Subject

CONTENT = {
    "اللغة العربية": {
        "مقدمة الدرس": (
            "في هذا الدرس سنتعرّف على موضوع جديد من موضوعات اللغة العربية، "
            "ونستعرض أهدافه الأساسية قبل الانتقال إلى الشرح التفصيلي. "
            "احرص على قراءة النص المصاحب وتدوين الكلمات الجديدة."
        ),
        "الشرح التفصيلي": (
            "نتناول هنا القاعدة اللغوية أو النص الأدبي بشرح مبسّط، مع أمثلة "
            "متعددة توضّح كيفية التطبيق. لاحظ الفرق بين الحالات المختلفة "
            "وحاول إعراب الجمل الموضحة في الأمثلة بنفسك."
        ),
        "تمارين وتطبيقات": (
            "حان وقت التطبيق العملي: أجب عن الأسئلة المرفقة، واكتب جملًا "
            "من إنشائك تستخدم فيها القاعدة التي درستها. راجع إجاباتك مع "
            "معلم المادة في الحصة القادمة."
        ),
    },
    "الرياضيات": {
        "مقدمة الدرس": (
            "سنبدأ هذا الدرس بمراجعة سريعة للمفاهيم السابقة المرتبطة "
            "بموضوعنا الجديد، ثم نوضّح الهدف من الدرس والخطوات التي "
            "سنتبعها للوصول إليه."
        ),
        "الشرح التفصيلي": (
            "نشرح هنا القانون أو الطريقة الحسابية خطوة بخطوة مع مثال محلول "
            "بالتفصيل. تأكد من فهم كل خطوة قبل الانتقال للتي تليها، ولا "
            "تتردد في إعادة المثال بنفسك على ورقة خارجية."
        ),
        "تمارين وتطبيقات": (
            "حل التمارين المرفقة بالترتيب من الأسهل إلى الأصعب. إذا "
            "واجهت صعوبة في مسألة معينة، ارجع إلى الشرح التفصيلي وراجع "
            "الخطوات مرة أخرى قبل المتابعة."
        ),
    },
    "العلوم": {
        "مقدمة الدرس": (
            "في هذا الدرس نستكشف ظاهرة علمية جديدة، ونطرح بعض الأسئلة "
            "التي سنجيب عنها خلال الشرح. حاول التفكير في إجابات مبدئية "
            "قبل قراءة المحتوى."
        ),
        "الشرح التفصيلي": (
            "نوضّح هنا المفهوم العلمي بالتفصيل مع رسم توضيحي ووصف للتجربة "
            "أو الظاهرة المرتبطة به. لاحظ العلاقة بين السبب والنتيجة في "
            "كل خطوة من خطوات الشرح."
        ),
        "تمارين وتطبيقات": (
            "أجب عن أسئلة المراجعة، وحاول ربط ما تعلمته بأمثلة من الحياة "
            "اليومية من حولك. ناقش إجاباتك مع زملائك في الحصة القادمة."
        ),
    },
    "اللغة الإنجليزية": {
        "مقدمة الدرس": (
            "In this lesson we introduce a new topic. Read the new "
            "vocabulary carefully and try to guess the meaning from "
            "context before checking the translation."
        ),
        "الشرح التفصيلي": (
            "Here we explain the grammar rule or reading text in detail, "
            "with several examples. Notice how the structure changes in "
            "each example, and try to build similar sentences yourself."
        ),
        "تمارين وتطبيقات": (
            "Now it's time to practice: complete the exercises attached "
            "to this lesson, then write two original sentences using "
            "today's vocabulary."
        ),
    },
    "التربية الدينية": {
        "مقدمة الدرس": (
            "نبدأ هذا الدرس بالتعرف على الموضوع وأهميته في حياتنا اليومية، "
            "ونذكر الهدف الذي نسعى للوصول إليه من خلال هذا الدرس."
        ),
        "الشرح التفصيلي": (
            "نستعرض هنا الموضوع بالتفصيل مع الاستشهاد بالأدلة المناسبة، "
            "ونوضّح كيف ينعكس هذا المفهوم على سلوكنا وتعاملنا مع من حولنا."
        ),
        "تمارين وتطبيقات": (
            "ناقش مع زملائك في الفصل كيف يمكن تطبيق ما تعلمته اليوم في "
            "حياتك، واكتب موقفًا واحدًا تعرضت له يرتبط بموضوع الدرس."
        ),
    },
}


def run():
    app = create_app()
    with app.app_context():
        updated = 0
        skipped = 0
        lessons = (
            db.session.query(Lesson)
            .join(Course, Lesson.course_id == Course.id)
            .join(Subject, Course.subject_id == Subject.id)
            .add_columns(Subject.name.label("subject_name"))
            .all()
        )
        for lesson, subject_name in lessons:
            bank = CONTENT.get(subject_name)
            if not bank:
                skipped += 1
                continue
            # lesson.title looks like "مقدمة الدرس 1" / "الشرح التفصيلي 2" ...
            matched_key = None
            for key in bank:
                if lesson.title.startswith(key):
                    matched_key = key
                    break
            if not matched_key:
                skipped += 1
                continue
            lesson.body = bank[matched_key]
            updated += 1
        db.session.commit()
        print(f"Updated: {updated} | Skipped (no match): {skipped}")


if __name__ == "__main__":
    run()
