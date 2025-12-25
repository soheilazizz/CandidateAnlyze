import os
import io
from datetime import date
from pathlib import Path

import streamlit as st
from openai import OpenAI

# ---------------- UI (RTL + Font) ----------------
st.set_page_config(page_title="ارزیابی کاندیدا", page_icon="🧠", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;600;700&display=swap');

html, body, [class*="css"]  {
  font-family: 'Vazirmatn', sans-serif;
}

.rtl { direction: rtl; text-align: right; }
.card {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.08);
  padding: 18px 18px;
  border-radius: 16px;
}
.small { font-size: 0.92rem; opacity: .85; }
.kpi {
  display: inline-block;
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.15);
  margin-left: 8px;
  margin-bottom: 8px;
  font-size: 0.92rem;
}
hr { border: none; height: 1px; background: rgba(255,255,255,0.10); margin: 16px 0; }
.stButton>button {
  border-radius: 12px;
  padding: 10px 16px;
  font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# ---------------- Helpers: extract text ----------------
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
        raise RuntimeError("کلید AVALAI_API_KEY در Secrets ست نشده.")

    client = OpenAI(base_url="https://api.avalai.ir/v1", api_key=api_key)

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
    if not api_key:
        raise RuntimeError("کلید AVALAI_API_KEY در Secrets ست نشده.")

    client = OpenAI(base_url="https://api.avalai.ir/v1", api_key=api_key)

    SYSTEM = "You are a strict, evidence-based HR evaluator. Be concise, structured, and avoid fluff."

    ASR_NOTE_FA = """
متن مصاحبه زیر خروجی خام تبدیل گفتار به متن (ASR) است و ممکن است شامل غلط املایی،
شکست کلمات، تکرار، یا خطاهای نگارشی باشد که ناشی از سیستم ASR است نه فرد مصاحبه‌شونده.
کیفیت زبان/املا را معیار قضاوت قرار نده. خطاهای متنی را نویز فرض کن.
"""

    FORMAT_SPEC = f"""
گزارش ارزیابی کاندیدا — نسخه یک‌صفحه‌ای (فارسی)

نام کاندیدا: (از رزومه استخراج کن؛ اگر نبود "نامشخص")
عنوان شغل: (از JD استخراج کن؛ اگر نبود "نامشخص")
تاریخ گزارش: {date.today().strftime("%Y-%m-%d")}
منابع بررسی: رزومه + فایل صوتی مصاحبه (خروجی ASR)

1) جمع‌بندی مدیریتی
- امتیاز تناسب کلی (Fit Score): XX/100 | سطح اطمینان: کم/متوسط/بالا
- پیشنهاد: Yes / No / Maybe (در صورت نیاز مشروط)
- چرا مثبت؟ (۲-۳ جمله)
- ریسک اصلی: (۱-۲ جمله)

2) نقاط قوت کلیدی (Strengths)
3) نقاط ضعف / ریسک‌ها (Weaknesses & Risks)

4) تحلیل تناسب مهارتی (Resume vs JD)
| نیاز شغلی | شواهد از رزومه/مصاحبه | میزان تطابق |
|---|---|---|
| ... | ... | پایین/متوسط/بالا |

- شکاف‌ها (Gaps): 2 تا 4 مورد با Impact: Low/Medium/High

5) تحلیل مصاحبه (سبک کاری از لحن و پاسخ‌ها)
- ساختار پاسخ‌گویی/شفافیت/مالکیت/ریسک‌های ارتباطی + دلیل کوتاه
- 2 Quote کوتاه

6) سازگاری ادعاها (Resume vs Interview)
7) پیشنهاد برای دور بعد (سوالات هدفمند)
8) نتیجه نهایی

مبنای Fit Score را صریح و ساده توضیح بده:
- 4 معیار: درک استراتژیک، تحلیل و تصمیم‌گیری، نگاه اجرایی، نشانه‌های رفتاری
- برای هر معیار: امتیاز + شواهد + دلیل
"""

    prompt = f"""
{FORMAT_SPEC}

قوانین:
- فقط بر اساس سه ورودی قضاوت کن: JD، رزومه، متن مصاحبه
- متن مصاحبه ASR خام است: {ASR_NOTE_FA}
- اگر داده نداریم: "نامشخص/یافت نشد"
- از قطعیت‌نمایی روانشناسانه پرهیز کن؛ نشانه‌ها را احتمالی بیان کن.

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
        temperature=0.2,
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


# ---------------- Header ----------------
st.markdown("""
<div class="rtl">
  <h1>🧠 ارزیابی کاندیدا</h1>
  <div class="small">ورودی: فایل صوت/ویدئو مصاحبه + رزومه + آگهی شغلی → خروجی: گزارش ساختاریافته + فایل Word</div>
</div>
<hr/>
""", unsafe_allow_html=True)

# ---------------- Layout ----------------
left, right = st.columns([1, 1], gap="large")

with left:
    st.markdown('<div class="card rtl">', unsafe_allow_html=True)
    st.subheader("1) ورودی‌ها")

    audio = st.file_uploader("فایل صوت/ویدئو مصاحبه", type=["mp3","wav","m4a","mp4","mpeg","mpga","ogg","oga","webm","flac"])
    resume = st.file_uploader("رزومه (pdf/docx/txt)", type=["pdf","docx","txt"])
    jd = st.file_uploader("آگهی شغلی (pdf/docx/txt)", type=["pdf","docx","txt"])

    st.markdown('<div class="small">نکته: متن مصاحبه خروجی خام ASR است؛ غلط‌ املایی را معیار قضاوت قرار نمی‌دهیم.</div>', unsafe_allow_html=True)

    run = st.button("✅ تولید گزارش", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="card rtl">', unsafe_allow_html=True)
    st.subheader("2) خروجی")
    st.markdown('<div class="small">پس از تولید، متن گزارش اینجا نمایش داده می‌شود و فایل Word قابل دانلود خواهد بود.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ---------------- Run pipeline ----------------
if run:
    if not (audio and resume and jd):
        st.error("هر ۳ فایل را آپلود کن.")
        st.stop()

    progress = st.progress(0, text="شروع فرآیند...")

    try:
        progress.progress(15, text="تبدیل صوت به متن...")
        interview_text = transcribe_audio_bytes(audio.getvalue(), audio.name)

        progress.progress(40, text="استخراج متن رزومه و آگهی شغلی...")
        resume_text = extract_text_from_upload(resume)
        jd_text = extract_text_from_upload(jd)

        progress.progress(70, text="تولید گزارش نهایی...")
        report_text = generate_report(resume_text, jd_text, interview_text)

        progress.progress(90, text="ساخت فایل Word...")
        docx_bytes = report_to_docx_bytes(report_text)

        progress.progress(100, text="انجام شد ✅")

        st.markdown("<hr/>", unsafe_allow_html=True)

        # KPIs quick extraction (simple)
        st.markdown('<div class="rtl">', unsafe_allow_html=True)
        st.markdown("### خلاصه سریع")
        st.markdown('<span class="kpi">✅ گزارش تولید شد</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.text_area("متن گزارش", report_text, height=420)

        st.download_button(
            "⬇️ دانلود گزارش Word",
            data=docx_bytes,
            file_name="candidate_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"خطا: {e}")
