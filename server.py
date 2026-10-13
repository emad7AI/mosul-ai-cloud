"""
===================================================
  الموصل AI - خادم السحابة المتكامل (Render Web Service)
  الإصدار المطور: v5.0 (2026)
  
  الميزات الأساسية:
  1. وكيل التعليقات الذكي (24/7):
     - يراقب التعليقات الأساسية والردود المتفرعة (Nested Replies)
     - يرد بلهجة مصلاوية/عراقية لطيفة وذكية
     - يضع أي أحرف/كلمات إنكليزية وأي أرقام بين قوسين ( ) تلقائياً
     - معالجة آمنة لبيانات فيسبوك بدون أي توقف أو أخطاء
  
  2. وكيل الأخبار الذكي والموزع حسب الأهمية:
     - أخبار التكنولوجيا (Axia_Tech): منشور واحد كل 6 ساعات
     - جريدة الصباح (alsbaahiq):
       * فحص كل 5-10 دقائق
       * أخبار الموصل ونينوى أو الرواتب والتعيينات: نشر فوري ومباشر!
       * الأخبار العامة المهمة: منشور واحد كل 3 ساعات فقط
     - جمال البدراني (jamal_albadrany):
       * أخبار عاجلة ومهمة للموصل: نشر فوري ومباشر!
       * الأخبار العادية: منشور كل ساعتين حسب الأهمية
     - صياغة فائقة الاختصار (كبسولة سريعة أقل من 35 كلمة)
     - وضع كل الأرقام والكلمات الإنكليزية بين قوسين ( )
===================================================
"""
import os, sys, time, json, threading, re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
import google.genai as genai
from google.genai import types

# ===== إعدادات الصفحة وجوجل (تُقرأ بأمان من متغيرات البيئة لمنع كشفها) =====
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "1322945474237295")
FACEBOOK_PAGE_TOKEN = os.getenv("FACEBOOK_PAGE_TOKEN", "")

# جلب مفاتيح جيميناي من متغيرات البيئة (Render) أو الإعدادات المحلية
gemini_env = os.getenv("GEMINI_API_KEY", "")
if gemini_env:
    GEMINI_KEYS = [k.strip() for k in gemini_env.split(",") if k.strip()]
else:
    try:
        from config.settings import GEMINI_KEYS as LOCAL_KEYS, FACEBOOK_PAGE_TOKEN as LOCAL_FB_TOKEN
        GEMINI_KEYS = LOCAL_KEYS
        if not FACEBOOK_PAGE_TOKEN:
            FACEBOOK_PAGE_TOKEN = LOCAL_FB_TOKEN
    except:
        GEMINI_KEYS = []

MODELS_FALLBACK = ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.7-flash"]
PAGE_NAME = "الموصل AI"

# فترات التوقيت (بالثواني)
TECH_INTERVAL = 6 * 3600          # كل 6 ساعات منشور تقني واحد
ALSABAH_GENERAL_INTERVAL = 3 * 3600  # كل 3 ساعات منشور عام من الصباح إذا لم يوجد خبر عاجل
JAMAL_REGULAR_INTERVAL = 2 * 3600    # كل ساعتين منشور اعتيادي من جمال البدراني

# سجلات التوقيت والذاكرة
TIMESTAMPS = {
    "Axia_Tech": 0.0,
    "alsbaahiq_general": 0.0,
    "jamal_regular": 0.0
}

SYSTEM_STATE = {
    "bot_enabled": True,
    "last_comment_check": "لم يبدأ بعد",
    "last_news_check": "لم يبدأ بعد",
    "last_news_post": "لم ينشر بعد",
    "comments_replied_count": 0,
    "news_posted_count": 0
}

# ملف حفظ التعليقات لتفادي التكرار بعد إعادة التشغيل
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)
REPLIED_FILE = os.path.join(DATA_DIR, "replied_comments.json")
PUBLISHED_NEWS_FILE = os.path.join(DATA_DIR, "published_news.json")

def load_json_set(file_path: str) -> set:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_json_set(file_path: str, data_set: set):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(list(data_set), f)
    except Exception as e:
        print(f"Error saving {file_path}: {e}")

replied_comments_memory = load_json_set(REPLIED_FILE)
published_news_memory = load_json_set(PUBLISHED_NEWS_FILE)

# ===== دالة التنسيق الاحترافية للأقواس =====
def format_text_parentheses(text: str) -> str:
    """
    تنسيق فائق الدقة:
    - يضع الجملة الإنكليزية كاملة بين قوسين (إذا كانت جملة) أو الكلمة المنفردة (إذا كانت كلمة).
    - يضع الأرقام المكتوبة كأرقام ونسب مئوية مثل (2026)، (5%)، (24) بين قوسين.
    - لا يضع الكلمات العربية المكتوبة مثل "مليون" أو "آلاف" بين أقواس نهائياً.
    - يحمي الروابط والهاشتاغات وما هو بين قوسين مسبقاً من التكرار.
    """
    if not text:
        return ""

    text = re.sub(r'\(\s*\((.*?)\)\s*\)', r'(\1)', text)
    protected = []
    def save_item(m):
        idx = len(protected)
        protected.append(m.group(0))
        return chr(0xE000 + idx)

    # 1. حماية الروابط
    text = re.sub(r'https?://\S+', save_item, text)
    # 2. حماية الهاشتاغات
    text = re.sub(r'#[\w_]+', save_item, text)
    # 3. حماية ما هو بين قوسين مسبقاً
    text = re.sub(r'\([^\(\)\n\r]+\)', save_item, text)

    # 4. وضع الجمل والعبارات الإنكليزية الكاملة أو الكلمات المنفردة بين قوسين
    def wrap_en(m):
        s = m.group(0).strip()
        if s:
            return f"({s})"
        return s

    text = re.sub(r'[A-Za-z][A-Za-z0-9\s,\.\'\-_/]*(?:[A-Za-z0-9])|[A-Za-z]', wrap_en, text)

    # 5. وضع الأرقام والنسب المئوية بين قوسين (أرقام فقط وليست كلمات عربية مثل مليون)
    text = re.sub(r'\b\d+(?:[/\.,]\d+)?%?', lambda m: f"({m.group(0)})", text)

    # 6. استعادة العناصر المحمية
    for idx, orig in enumerate(protected):
        placeholder = chr(0xE000 + idx)
        text = text.replace(placeholder, orig)

    # 7. تنظيف نهائي للأقواس
    text = re.sub(r'\(\s*\((.*?)\)\s*\)', r'(\1)', text)
    text = re.sub(r'\(\s+', '(', text)
    text = re.sub(r'\s+\)', ')', text)
    text = re.sub(r'\(([^)]+)\)%', r'(\1%)', text)
    return text

def wrap_en_and_numbers(text: str) -> str:
    return format_text_parentheses(text)


# ===== مساعد جيميناي متعدد المفاتيح والنماذج المقاوم للضغط =====
def call_gemini(prompt: str, max_tokens: int = 350, temperature: float = 0.7) -> str | None:
    for key in GEMINI_KEYS:
        client = genai.Client(api_key=key)
        for model in MODELS_FALLBACK:
            try:
                res = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_tokens
                    )
                )
                if res and res.text:
                    return res.text.strip()
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "429" in err_str:
                    continue  # جرب النموذج التالي أو المفتاح التالي
                elif "404" in err_str:
                    continue
                else:
                    break
    return None


if HAS_FASTAPI:
    app = FastAPI(title="Mosul AI Cloud Engine")

    # ===== لوحة التحكم من الموبايل =====
    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        status_badge = '<span style="color:#00ff88;font-weight:bold;">🟢 شغال 24/7</span>' if SYSTEM_STATE["bot_enabled"] else '<span style="color:#ff4444;font-weight:bold;">🔴 متوقف مؤقتاً</span>'
        toggle_btn_text = "إيقاف البوت مؤقتاً ⏸️" if SYSTEM_STATE["bot_enabled"] else "تشغيل البوت الآن ▶️"
        
        html_content = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم الموصل AI</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b1329; color: #f8fafc; text-align: center; padding: 20px; }}
        .card {{ background: #162447; border-radius: 18px; padding: 24px; max-width: 480px; margin: 15px auto; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #1f3a60; }}
        h1 {{ color: #00d2ff; font-size: 24px; margin-bottom: 6px; }}
        .status {{ font-size: 17px; margin: 14px 0; padding: 12px; background: #1f3158; border-radius: 12px; }}
        .btn {{ display: block; width: 100%; padding: 14px; margin: 10px 0; border: none; border-radius: 12px; font-size: 16px; font-weight: bold; cursor: pointer; text-decoration: none; box-sizing: border-box; }}
        .btn-toggle {{ background: #0077b6; color: white; }}
        .btn-news {{ background: #00b4d8; color: #0b1329; }}
        .stats {{ text-align: right; font-size: 14px; color: #94a3b8; line-height: 2.0; margin-top: 15px; border-top: 1px solid #2a4365; padding-top: 12px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🤖 مركز تحكم الموصل AI</h1>
        <p style="color:#94a3b8;font-size:13px;">إدارة التعليقات ونشر الأخبار التلقائي</p>
        
        <div class="status">الحالة العامة: {status_badge}</div>
        
        <a href="/toggle" class="btn btn-toggle">{toggle_btn_text}</a>
        <a href="/trigger-news" class="btn btn-news">📰 فحص ونشر خبر الآن فوراً</a>
        <a href="/trigger-comments" class="btn btn-toggle" style="background:#2ec4b6;">💬 فحص والرد على التعليقات الآن</a>
        
        <div class="stats">
            <div>⏱️ آخر فحص للتعليقات: <b>{SYSTEM_STATE["last_comment_check"]}</b></div>
            <div>🔍 آخر فحص للأخبار: <b>{SYSTEM_STATE["last_news_check"]}</b></div>
            <div>📢 آخر خبر منشور: <b>{SYSTEM_STATE["last_news_post"]}</b></div>
            <div>💬 ردود التعليقات المنجزة: <b>{SYSTEM_STATE["comments_replied_count"]}</b></div>
            <div>📑 إجمالي الأخبار المنشورة: <b>{SYSTEM_STATE["news_posted_count"]}</b></div>
        </div>
    </div>
</body>
</html>"""
        return html_content

    @app.get("/toggle")
    def toggle_bot():
        SYSTEM_STATE["bot_enabled"] = not SYSTEM_STATE["bot_enabled"]
        return HTMLResponse('<script>window.location.href="/";</script>')

    @app.get("/trigger-news")
    def trigger_news():
        threading.Thread(target=check_and_post_curated_news, args=(True,)).start()
        return HTMLResponse('<script>alert("جاري فحص القنوات ونشر الأخبار المستوفية للشروط فوراً..."); window.location.href="/";</script>')

    @app.get("/trigger-comments")
    def trigger_comments():
        threading.Thread(target=process_comments_once).start()
        return HTMLResponse('<script>alert("جاري فحص جميع المنشورات والرد على أي تعليقات جديدة..."); window.location.href="/";</script>')
else:
    app = None


# ===== محرك التعليقات الشامل (الأساسية والمتفرعة) =====
def process_comments_once():
    if not SYSTEM_STATE["bot_enabled"] or not FACEBOOK_PAGE_TOKEN:
        return

    try:
        SYSTEM_STATE["last_comment_check"] = datetime.now().strftime("%I:%M:%S %p")
        posts = []
        # 1. فحص المنشورات
        try:
            url_feed = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
            res_feed = requests.get(url_feed, params={
                "fields": "id,message,comments.limit(30){id,message,from,created_time,comments.limit(30){id,message,from,created_time}}",
                "access_token": FACEBOOK_PAGE_TOKEN,
                "limit": 15
            }, timeout=15).json()
            posts.extend(res_feed.get("data", []))
        except:
            pass

        # 2. فحص الصور
        try:
            url_photos = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
            res_photos = requests.get(url_photos, params={
                "type": "uploaded",
                "fields": "id,name,comments.limit(30){id,message,from,created_time,comments.limit(30){id,message,from,created_time}}",
                "access_token": FACEBOOK_PAGE_TOKEN,
                "limit": 10
            }, timeout=15).json()
            posts.extend(res_photos.get("data", []))
        except:
            pass
        for post in posts:
            post_context = post.get("message", "")
            top_comments = post.get("comments", {}).get("data", [])

            for t_comment in top_comments:
                t_id = t_comment.get("id")
                t_text = t_comment.get("message", "").strip()
                t_from = t_comment.get("from") or {}
                t_author = t_from.get("name", "متابع")
                t_author_id = str(t_from.get("id", ""))

                nested_comments = t_comment.get("comments", {}).get("data", [])

                # التحقق هل الصفحة ردت بالفعل على هذا التعليق الرئيسي
                page_replied_to_parent = any(
                    str((r.get("from") or {}).get("id", "")) == str(FACEBOOK_PAGE_ID)
                    or PAGE_NAME in (r.get("from") or {}).get("name", "")
                    for r in nested_comments
                )

                # 1. الرد على التعليق الرئيسي إذا لم يتم الرد عليه
                if t_id not in replied_comments_memory and t_text and t_author_id != str(FACEBOOK_PAGE_ID) and PAGE_NAME not in t_author:
                    if not page_replied_to_parent:
                        reply = generate_smart_comment_reply(post_context, t_text, t_author)
                        if reply:
                            post_comment_reply(t_id, reply)
                    replied_comments_memory.add(t_id)
                    save_json_set(REPLIED_FILE, replied_comments_memory)

                # 2. الرد على الردود المتفرعة (Nested Replies) داخل المحادثة
                for n_comment in nested_comments:
                    n_id = n_comment.get("id")
                    n_text = n_comment.get("message", "").strip()
                    n_from = n_comment.get("from") or {}
                    n_author = n_from.get("name", "متابع")
                    n_author_id = str(n_from.get("id", ""))

                    if n_id in replied_comments_memory or not n_text:
                        continue
                    if n_author_id == str(FACEBOOK_PAGE_ID) or PAGE_NAME in n_author:
                        continue

                    thread_context = f"المنشور:\n{post_context[:300]}\n\nالتعليق الأساسي:\n{t_text}"
                    n_reply = generate_smart_comment_reply(thread_context, n_text, n_author)
                    if n_reply:
                        post_comment_reply(n_id, n_reply)
                    replied_comments_memory.add(n_id)
                    save_json_set(REPLIED_FILE, replied_comments_memory)

    except Exception as e:
        print(f"Comments engine error: {e}")


def generate_smart_comment_reply(context_text: str, comment_text: str, author: str) -> str | None:
    now_year = "2026"
    prompt = f"""أنت محرر الذكاء الاصطناعي الذكي، اللبق، والخبير لصفحة "{PAGE_NAME}" الرسمية على فيسبوك الخاصة بمدينة الموصل ومحافظة نينوى.
نحن الآن في عام ({now_year}).

مهمتك:
قراءة المنشور وفهم سياقه بدقة، ثم قراءة تعليق المتابع ({author}) وتقديم رد ذكي، شافي، وافٍ، ومباشر يجيب عن سؤاله ويخدمه بأعلى درجات اللباقة والاحترام.

سياق المنشور وتفاصيله الكاملة:
---
{context_text[:2500] if context_text else "منشور عام لصفحة الموصل AI"}
---

تعليق المتابع ({author}):
"{comment_text}"

تعليمات صياغة الرد (حتمية وإلزامية):
1. **الفهم والشمولية**: اقرأ تعليق المتابع بعناية واربطه بتفاصيل المنشور أعلاه. إذا كان يسأل عن شروط، ضوابط، تفاصيل، أو استفسار توضيحي، اشرح له النقاط بدقة ووضوح وبشكل منظم ومفيد يغنيه عن البحث، واختم بجملة ترحيبية أو استفسار إن كان بحاجة لمزيد من المساعدة.
2. **الأسلوب واللغة**: تحدث بأسلوب عراقي/مصلاوي راقٍ وودود ومحترم (أو فصحى مبسطة لطيفة مثل: أهلاً وسهلاً بك أخي العزيز، تدلل، بخدمتك)، كأنك محرر ووكيل ذكي يمثل الصفحة بأفضل وجه.
3. **تجنب البتر والاختصار المفرط**: ممنوع نهائياً الردود المبتورة أو غير المكتملة أو التحيات الفارغة مثل "أهلاً بيك" وحدها دون إجابة. يجب أن تكتمل كل فكرة وجملة حتى نهايتها.
4. **قواعد الأقواس الإلزامية**:
   - أي جملة أو عبارة كاملة باللغة الإنكليزية، ضع الجملة كاملة بين قوسين: (مثل هذه الجملة).
   - أي كلمة إنكليزية منفردة أو حرف إنكليزي، ضعه بين قوسين مثل: (AI)، (DNA).
   - الأرقام المكتوبة كأرقام (digits) والنسب المئوية ضعها بين قوسين مثل: (2026)، (5%)، (24).
   - الأرقام المكتوبة ككلمات عربية مثل "مليون" أو "آلاف" أو "خمسة" لا تضعها بين أقواس أبداً.
5. إذا كان التعليق مسيئاً تماماً، اكتب فقط: SKIP.

الرد الكامل المتقن:"""

    raw_reply = call_gemini(prompt, max_tokens=1200, temperature=0.7)
    if not raw_reply or "SKIP" in raw_reply or len(raw_reply) < 5:
        return None

    # تطبيق الفلترة الإلزامية للأقواس
    return format_text_parentheses(raw_reply)


def post_comment_reply(comment_id: str, reply_text: str) -> bool:
    try:
        url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
        res = requests.post(url, data={
            "message": reply_text,
            "access_token": FACEBOOK_PAGE_TOKEN
        }, timeout=15).json()

        if "id" in res:
            SYSTEM_STATE["comments_replied_count"] += 1
            print(f"✅ تم الرد على التعليق {comment_id}: {reply_text[:50]}...")
            return True
        else:
            print(f"❌ فشل إرسال الرد للتعليق {comment_id}: {res}")
            return False
    except Exception as e:
        print(f"Post comment error: {e}")
        return False


def comments_loop():
    while True:
        process_comments_once()
        time.sleep(20)  # فحص سريع كل 20 ثانية لسرعة الاستجابة الفائقة


# ===== محرك الأخبار المنظم حسب الأهمية والمصادر =====
CHANNELS = [
    {"source": "alsbaahiq", "url": "https://t.me/s/alsbaahiq"},
    {"source": "jamal_albadrany", "url": "https://t.me/s/jamal_albadrany"},
    {"source": "Axia_Tech", "url": "https://t.me/s/Axia_Tech"}
]

# كلمات مفتاحية دالة على أخبار الموصل والرواتب العاجلة لجريدة الصباح
MOSUL_AND_SALARY_KEYWORDS = [
    "موصل", "نينوى", "الحدباء", "سنجار", "تلعفر", "القيارة", "مخمور", "الحمدانية", "سهل نينوى", "بادوش",
    "رواتب", "راتب", "تعيينات", "تعيين", "عقود", "متقاعدين", "تقاعد", "رعاية اجتماعية", "الحماية الاجتماعية",
    "سلم الرواتب", "صرف الرواتب", "وزارة المالية", "مصرف الرافدين", "مصرف الرشيد"
]

# كلمات مفتاحية للأخبار العاجلة والطارئة لجمال البدراني
JAMAL_URGENT_KEYWORDS = [
    "عاجل", "طارئ", "تعطيل الدوام", "عطلة رسمية", "إغلاق الجسر", "فتح الجسر", "أمطار", "سيول", "حظر",
    "مجلس محافظة نينوى", "محافظ نينوى", "طوارئ", "خلية الأزمة", "انقطاع الماء", "انقطاع الكهرباء"
]

def check_and_post_curated_news(force: bool = False):
    if not SYSTEM_STATE["bot_enabled"] and not force:
        return

    now_t = time.time()
    SYSTEM_STATE["last_news_check"] = datetime.now().strftime("%I:%M:%S %p")

    for ch in CHANNELS:
        source_name = ch["source"]
        url = ch["url"]

        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message")

            for msg in reversed(messages):
                post_id = msg.get("data-post")
                if not post_id or post_id in published_news_memory:
                    continue

                text_elem = msg.find("div", class_="tgme_widget_message_text")
                if not text_elem or len(text_elem.get_text().strip()) < 35:
                    continue

                raw_text = text_elem.get_text(separator="\n").strip()

                # تصنيف وتوقيت كل مصدر:
                should_publish_now = False
                post_type = "normal"

                if source_name == "Axia_Tech":
                    # قاعدة التكنولوجيا: كل 6 ساعات منشور واحد
                    if force or (now_t - TIMESTAMPS["Axia_Tech"] >= TECH_INTERVAL):
                        should_publish_now = True
                        post_type = "tech"
                    else:
                        continue  # لم يحن وقت المنشور التقني بعد

                elif source_name == "alsbaahiq":
                    # فحص هل الخبر يخص الموصل أو الرواتب والتعيينات
                    is_urgent_topic = any(kw in raw_text for kw in MOSUL_AND_SALARY_KEYWORDS)
                    if is_urgent_topic:
                        # نشر فوري ومباشر!
                        should_publish_now = True
                        post_type = "alsbaahiq_urgent"
                    else:
                        # خبر عام مهم: كل 3 ساعات منشور واحد فقط
                        if force or (now_t - TIMESTAMPS["alsbaahiq_general"] >= ALSABAH_GENERAL_INTERVAL):
                            should_publish_now = True
                            post_type = "alsbaahiq_general"
                        else:
                            continue

                elif source_name == "jamal_albadrany":
                    # فحص هل الخبر عاجل أو طارئ للموصل
                    is_urgent_jamal = any(kw in raw_text for kw in JAMAL_URGENT_KEYWORDS)
                    if is_urgent_jamal:
                        should_publish_now = True
                        post_type = "jamal_urgent"
                    else:
                        # خبر موصلي اعتيادي: كل ساعتين كحد أدنى حسب الأهمية
                        if force or (now_t - TIMESTAMPS["jamal_regular"] >= JAMAL_REGULAR_INTERVAL):
                            should_publish_now = True
                            post_type = "jamal_regular"
                        else:
                            continue

                if not should_publish_now:
                    continue

                # صياغة الخبر بالذكاء الاصطناعي مع فرض الشروط الصارمة
                formatted_post = format_news_post(source_name, raw_text, post_type)
                if formatted_post and "SKIP" not in formatted_post:
                    # نشر الخبر على فيسبوك كنص نقي
                    if post_to_fb(formatted_post):
                        published_news_memory.add(post_id)
                        save_json_set(PUBLISHED_NEWS_FILE, published_news_memory)

                        # تحديث التوقيتات المناسبة
                        if post_type == "tech":
                            TIMESTAMPS["Axia_Tech"] = now_t
                        elif post_type == "alsbaahiq_general":
                            TIMESTAMPS["alsbaahiq_general"] = now_t
                        elif post_type == "jamal_regular":
                            TIMESTAMPS["jamal_regular"] = now_t

                        SYSTEM_STATE["news_posted_count"] += 1
                        SYSTEM_STATE["last_news_post"] = f"[{source_name}] " + datetime.now().strftime("%I:%M %p")
                        print(f"📢 تم نشر خبر جديد ({post_type}) بنجاح: {post_id}")
                        return  # نكتفي بخبر واحد في هذه الدورة لمنع التزاحم
                else:
                    published_news_memory.add(post_id)
                    save_json_set(PUBLISHED_NEWS_FILE, published_news_memory)

        except Exception as e:
            print(f"News check error on {source_name}: {e}")


def format_news_post(source: str, raw_text: str, post_type: str) -> str | None:
    prompt = f"""أنت رئيس تحرير صفحة فيسبوك "{PAGE_NAME}".
المصدر: ({source})
نوع التوزيع: ({post_type})

الخبر الخام:
\"\"\"
{raw_text}
\"\"\"

معايير الفلترة والموافقة:
1. إذا كان المصدر (alsbaahiq):
   - اقبل فوراً إذا كان يخص نينوى/الموصل، أو صرف وتعديل الرواتب، أو تعيينات وعقود، أو رعاية اجتماعية.
   - إذا كان خبراً عاماً، اقبل فقط إذا كان قراراً حكومياً حيوياً يهم المواطن. ارفض الأخبار السياسية الحزبية أو الرياضة: أرجع SKIP.
2. إذا كان المصدر (jamal_albadrany):
   - اقبل القرارات، الجسور، الخدمات، العطل، الأمطار، والطوارئ في الموصل.
   - ارفض الحوادث الشخصية والوفيات والشائعات والآراء: أرجع SKIP.
3. إذا كان المصدر (Axia_Tech):
   - اقبل التطورات العملية في الذكاء الاصطناعي والتكنولوجيا. ارفض الإعلانات: أرجع SKIP.

الشروط الصارمة للصياغة:
1. كبسولة سريعة جداً: عنوان بارز سطر واحد مع إيموجي.
2. سطران اثنان فقط (نقطتان برصاصة •) تلخصان جوهر الخبر في أقل من 35 كلمة!
3. سؤال تفاعلي ذكي وقصير جداً للمتابعين.
4. الهاشتاغات: #الموصل_AI #الموصل #نينوى (أو #تكنولوجيا للأخبار التقنية).
5. شرط التنسيق الحتمي: أي كلمة باللغة الإنكليزية أو أي حرف إنكليزي، وأي رقم (سنة، نسبة، عدد)، يجب أن يكون بين قوسين حصراً مثل: (AI)، (2026)، (5)، (100).

أرجع المنشور المصاغ مباشرة، أو كلمة SKIP فقط إذا لم يستوفِ المعايير:"""

    raw_news = call_gemini(prompt, max_tokens=250, temperature=0.2)
    if not raw_news or "SKIP" in raw_news or len(raw_news) < 30:
        return None

    # تطبيق فاحص الأقواس الإلزامي لضمان عدم فوات أي رقم أو كلمة إنكليزية
    return wrap_en_and_numbers(raw_news)


def post_to_fb(message: str) -> bool:
    try:
        url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
        r = requests.post(url, data={
            "message": message,
            "access_token": FACEBOOK_PAGE_TOKEN
        }, timeout=20).json()
        return "id" in r
    except:
        return False


# ===== محرك مجدول الأخبار (فحص دوري كل 6 دقائق) =====
def news_scheduler_loop():
    while True:
        check_and_post_curated_news()
        time.sleep(360)  # فحص سريع كل 6 دقائق لاقتناص أي خبر عاجل للموصل أو الرواتب فوراً


# تشغيل المحركات في الخلفية عند بدء تشغيل السيرفر
threading.Thread(target=comments_loop, daemon=True).start()
threading.Thread(target=news_scheduler_loop, daemon=True).start()

if __name__ == "__main__":
    if HAS_FASTAPI and app:
        port = int(os.environ.get("PORT", 8080))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        while True:
            time.sleep(3600)
