import os
import io
from datetime import date
from pathlib import Path

import streamlit as st
from openai import OpenAI

# --------- Helpers: extract text ----------
def extract_text_from_upload(uploaded_file) -> str:
    name = uploaded_file.name.lower()

    if name.endswith(".txt"):
        return uploaded_file.getvalue().decode("utf-8", errors="ignore")

    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(uploaded_file.getvalue()))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)

    if name.endswith(".docx"):
        from docx import Document
        tmp = io.BytesIO(uploaded_file.getvalue())
        doc = Document(tmp)
        return "\n".join([p.text for p in doc.paragraphs])

    raise ValueError("فرمت رزومه/JD باید یکی از pdf/docx/txt باشد.")


def transcribe_audio_bytes(file_bytes: bytes, filename: str) -> str:
    api_key = os.getenv("AVALAI_API_KEY")
    if not api_key:
        raise RuntimeError("AVALAI_API_KEY در Secrets ست نشده.")

    client = OpenAI(base_url="https://api.avalai.ir/v1", api_key=api_key)

    # موقت روی دیسک (برای SDK)
    tmp_path = Path("/tmp") / filename
    tmp_path.write_bytes(file_bytes)

    try:
        with open(tmp_path, "rb") as f:
            t = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="text",
                language="fa",
            )
        return str(t)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def generate_report(resume_text: str, jd_text: str, interview_asr: str) -> str:
    api_key = os.getenv("AVALAI_API_KEY")
    client = OpenAI(base_url="https://api.avalai.ir/v1", api_key=api_key)

    SYSTEM = "You are a strict, evidence-based HR & business strategy interviewer. Be concise and avoid fluff."

    ASR_NOTE_FA = """
متن مصاحبه زیر خروجی خام تبدیل گفتار به متن (ASR) است و ممکن است شامل غلط املایی،
شکست کلمات، تکرار، یا خطاهای نگارشی باشد که ناشی از سیستم ASR است نه فرد مصاحبه‌شونده.
کیفیت زبان/املا را معیار قضاوت قرار نده. خطاهای متنی را نویز فرض کن.
"""

    FORMAT_SPEC = f"""
گزارش ارزیابی کاندیدا — نسخه یک‌صفحه‌ای (فارسی)

قالب خروجی باید دقیقاً بخش‌های زیر را داشته باشد و شماره‌گذاری حفظ شود:

نام کاندیدا: (از رزومه استخراج کن؛ اگر نبود بنویس "نامشخص")
عنوان شغل: (از JD استخراج کن)
تاریخ گزارش: {date.today().strftime("%Y-%m-%d")}
منابع بررسی: رزومه + فایل صوتی مصاحبه (خروجی ASR)

1) جمع‌بندی مدیریتی
- امتیاز تناسب کلی (Fit Score): XX/100 | سطح اطمینان: کم/متوسط/بالا
- پیشنهاد: Yes / No / Maybe (مشروط/غیرمشروط)
- چرا مثبت؟ (۲-۳ جمله)
- ریسک اصلی: (۱-۲ جمله)

2) نقاط قوت کلیدی (Strengths)

3) نقاط ضعف / ریسک‌ها (Weaknesses & Risks)

4) تحلیل تناسب مهارتی (Resume vs JD)
- Must-have ها (کلیدی): یک جدول 3 ستونه با سرفصل‌های:
  نیاز شغلی | شواهد از رزومه/مصاحبه | میزان تطابق (پایین/متوسط/بالا)
- شکاف‌ها (Gaps): 2 تا 4 مورد با Impact: Low/Medium/High

5) تحلیل مصاحبه (نشانه‌های سبک کاری از لحن و پاسخ‌ها)
- ساختار پاسخ‌گویی/شفافیت/مالکیت/ریسک‌های ارتباطی + دلیل کوتاه
- نمونه شواهد: دو Quote کوتاه

6) سازگاری ادعاها (Resume vs Interview)
7) پیشنهاد برای دور بعد (سوالات هدفمند)
8) نتیجه نهایی

مبنای Fit Score را صریح و ساده توضیح بده:
- چهار معیار: درک استراتژیک، تحلیل و تصمیم‌گیری، نگاه اجرایی، نشانه‌های رفتاری
- شواهد هر معیار را ذکر کن و بگو چرا امتیاز بالا/پایین شده.
"""

    prompt = f"""
{FORMAT_SPEC}

قوانین حیاتی:
- فقط بر اساس این سه ورودی قضاوت کن: JD، رزومه، متن مصاحبه
- متن مصاحبه ASR خام است: {ASR_NOTE_FA}
- از شعار دوری کن؛ شواهد کوتاه بده.
- اگر چیزی در داده‌ها نیست، "نامشخص/یافت نشد" بنویس.

[JD]
{jd_text}

[RESUME]
{resume_text}

[INTERVIEW_ASR]
{interview_asr}
"""

    resp = client.chat.completions.create(
        model=os.getenv("AVALAI_TEXT_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    return resp.choices[0].message.content


def report_to_docx_bytes(report_text: str) -> bytes:
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document()

    def add_rtl(text, bold=False, size=11):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        r = p.add_run(text)
        r.bold = bold
        r.font.size = Pt(size)

    add_rtl("گزارش ارزیابی کاندیدا — نسخه یک‌صفحه‌ای", bold=True, size=14)
    doc.add_paragraph("")

    # ساده: خط به خط
    for line in report_text.splitlines():
        line = line.strip()
        if not line:
            doc.add_paragraph("")
            continue
        is_section = any(line.startswith(f"{k})") for k in range(1, 9))
        is_meta = line.startswith("نام کاندیدا") or line.startswith("عنوان شغل") or line.startswith("تاریخ گزارش") or line.startswith("منابع بررسی")
        if is_section:
            add_rtl(line, bold=True, size=12)
        elif is_meta:
            add_rtl(line, bold=True, size=11)
        else:
            add_rtl(line, bold=False, size=11)

    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


# --------- UI ----------
st.set_page_config(page_title="Candidate Evaluator (FA)", page_icon="🧠", layout="centered")
st.title("🧠 ارزیابی کاندیدا از روی مصاحبه + رزومه + آگهی شغلی")

st.caption("آپلود ۳ فایل → تبدیل گفتار به متن → تحلیل ساختاریافته → خروجی Word")

audio = st.file_uploader("فایل صوت/ویدئو مصاحبه", type=["mp3","wav","m4a","mp4","mpeg","mpga","ogg","oga","webm","flac"])
resume = st.file_uploader("رزومه (pdf/docx/txt)", type=["pdf","docx","txt"])
jd = st.file_uploader("آگهی شغلی (pdf/docx/txt)", type=["pdf","docx","txt"])

if st.button("تولید گزارش"):
    if not (audio and resume and jd):
        st.error("هر ۳ فایل را آپلود کن.")
        st.stop()

    with st.spinner("در حال تبدیل صوت به متن..."):
        interview_text = transcribe_audio_bytes(audio.getvalue(), audio.name)

    with st.spinner("در حال استخراج متن رزومه و JD..."):
        resume_text = extract_text_from_upload(resume)
        jd_text = extract_text_from_upload(jd)

    with st.spinner("در حال تولید گزارش نهایی..."):
        report_text = generate_report(resume_text, jd_text, interview_text)

    st.success("گزارش تولید شد.")
    st.text_area("خروجی گزارش", report_text, height=420)

    docx_bytes = report_to_docx_bytes(report_text)
    st.download_button(
        "دانلود گزارش Word",
        data=docx_bytes,
        file_name="candidate_report.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
