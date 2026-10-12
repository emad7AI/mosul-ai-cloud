"""
===================================================
  الموصل AI - خادم السحابة المتكامل (Render Web Service)
  يجمع بين:
  1. لوحة تحكم ويب خفيفة (Dashboard) للتحكم من الهاتف
  2. وكيل التعليقات التلقائي (يعمل 24/7)
  3. وكيل أخبار جريدة الصباح (ينشر كل 3 ساعات)
===================================================
"""
import os, sys, time, json, threading, re
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# إعدادات الصفحة وجوجل (تُسحب من متغيرات البيئة أو الإعدادات)
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "61580822445112")
FACEBOOK_PAGE_TOKEN = os.getenv("FACEBOOK_PAGE_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PAGE_NAME = "الموصل AI"

# حالة النظام
SYSTEM_STATE = {
    "bot_enabled": True,
    "last_comment_check": "لم يبدأ بعد",
    "last_news_post": "لم ينشر بعد",
    "comments_replied_count": 0,
    "news_posted_count": 0
}

app = FastAPI(title="Mosul AI Cloud Engine")

# ===== مسار لوحة التحكم من الموبايل =====
@app.get("/", response_class=HTMLResponse)
def dashboard():
    status_badge = '<span style="color:#00ff88;font-weight:bold;">🟢 شغال 24/7</span>' if SYSTEM_STATE["bot_enabled"] else '<span style="color:#ff4444;font-weight:bold;">🔴 متوقف مؤقتاً</span>'
    toggle_btn_text = "إيقاف البوت مؤقتاً ⏸️" if SYSTEM_STATE["bot_enabled"] else "تشغيل البوت الآن ▶️"
    toggle_action = "/toggle"

    html_content = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة تحكم الموصل AI</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 20px; }}
        .card {{ background: #1e293b; border-radius: 16px; padding: 24px; max-width: 480px; margin: 20px auto; box-shadow: 0 10px 25px rgba(0,0,0,0.4); }}
        h1 {{ color: #38bdf8; font-size: 24px; margin-bottom: 8px; }}
        .status {{ font-size: 18px; margin: 16px 0; padding: 10px; background: #334155; border-radius: 10px; }}
        .btn {{ display: block; width: 100%; padding: 14px; margin: 12px 0; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; text-decoration: none; box-sizing: border-box; }}
        .btn-toggle {{ background: #0284c7; color: white; }}
        .btn-news {{ background: #10b981; color: white; }}
        .stats {{ text-align: right; font-size: 14px; color: #94a3b8; line-height: 1.8; margin-top: 15px; border-top: 1px solid #475569; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🤖 لوحة تحكم الموصل AI</h1>
        <p style="color:#94a3b8;font-size:14px;">مركز العمليات السحابي المستقل</p>
        
        <div class="status">الحالة: {status_badge}</div>
        
        <a href="{toggle_action}" class="btn btn-toggle">{toggle_btn_text}</a>
        <a href="/trigger-news" class="btn btn-news">📰 افحص وانشر خبر الآن فوراً</a>
        
        <div class="stats">
            <div>⏱️ آخر فحص للتعليقات: <b>{SYSTEM_STATE["last_comment_check"]}</b></div>
            <div>📢 آخر خبر منشور: <b>{SYSTEM_STATE["last_news_post"]}</b></div>
            <div>💬 ردود التعليقات المنجزة: <b>{SYSTEM_STATE["comments_replied_count"]}</b></div>
            <div>📑 عدد الأخبار المنشورة: <b>{SYSTEM_STATE["news_posted_count"]}</b></div>
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
    return HTMLResponse('<script>alert("جاري فحص القناتين ونشر الخبر المستوفي للشروط..."); window.location.href="/";</script>')


# ===== محرك الأخبار المزدوج (جريدة الصباح + جمال البدراني) =====
published_news_memory = set()

CHANNELS = [
    {"source": "jamal_albadrany", "url": "https://t.me/s/jamal_albadrany"},
    {"source": "alsbaahiq", "url": "https://t.me/s/alsbaahiq"}
]

def check_and_post_curated_news(force=False):
    if not SYSTEM_STATE["bot_enabled"] and not force:
        return

    try:
        for ch in CHANNELS:
            source_name = ch["source"]
            url = ch["url"]
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
                if not text_elem or len(text_elem.get_text().strip()) < 40:
                    continue

                raw_text = text_elem.get_text(separator="\n").strip()
                
                # فحص وجود صورة مرفقة
                photo_url = None
                photo_elem = msg.find("a", class_="tgme_widget_message_photo_wrap")
                if photo_elem and "background-image" in photo_elem.get("style", ""):
                    m = re.search(r"url\('?(.*?)'?\)", photo_elem["style"])
                    if m: photo_url = m.group(1)

                # التقييم والفلترة والصياغة المختصرة
                formatted_post = evaluate_and_format_news(source_name, raw_text)
                
                # إذا وافق الذكاء الاصطناعي وكان الخبر مستوفياً للشروط
                if formatted_post and "SKIP" not in formatted_post:
                    if post_to_fb(formatted_post, photo_url):
                        published_news_memory.add(post_id)
                        SYSTEM_STATE["news_posted_count"] += 1
                        SYSTEM_STATE["last_news_post"] = f"[{source_name}] " + datetime.now().strftime("%I:%M %p")
                        print(f"✅ تم نشر خبر معتمد من {source_name}: {post_id}")
                        return  # نكتفي بنشر خبر واحد معتمد لكل دورة
                else:
                    # تم تجاهل الخبر لأنه لا يستوفي شروط الأهمية أو المحلية
                    published_news_memory.add(post_id)

    except Exception as e:
        print(f"News engine error: {e}")


def evaluate_and_format_news(source: str, raw_text: str) -> str | None:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""أنت مدير تحرير صحفي لصفحة فيسبوك "{PAGE_NAME}".
المصدر: ({source})
الخبر الخام:
\"\"\"
{raw_text}
\"\"\"

معايير التصفية والفلترة الصارمة:
1. إذا كان المصدر (alsbaahiq): انشر إذا كان الخبر يخص محافظة نينوى أو مدينة الموصل، أو إذا كان يخص الملف المالي والمعيشي العراقي الحيوي (الرواتب، سلم الرواتب، سعر صرف الدولار والعملة، الموازنة، والقرارات الاقتصادية التي تمس جيب المواطن). إذا كان خبراً سياسياً عاماً أو بروتوكولياً لا يخص هذه المحاور أرجع: SKIP.
2. إذا كان المصدر (jamal_albadrany): انشر فقط الأخبار الحيوية والمهمة جداً للمواطن (رواتب، سلم الرواتب، تعيينات وعقود، عطل رسمية، قرارات مرورية أو أمنية عامة، مشاريع كبرى في الموصل). استبعد الأخبار الخارجية، التكهنات السياسية، والشؤون غير المؤثرة. إذا لم يكن مهماً أرجع: SKIP.

إذا كان الخبر يستحق النشر:
- صغه كخبر كبسولة قصير جداً ومكثف (عنوان بارز بإيموجي + سطرين أو 3 أسطر فقط للتفاصيل).
- التزم بالدقة التامة للأرقام والوقائع؛ إياك أن تختلق أو تدمج معلومات غير موجودة.
- احذف اسم المصدر والروابط الخارجية.
- أضف سؤالاً تفاعلياً قصيراً وهاشتاغات: #الموصل_AI #الموصل #نينوى.

أرجع إما المنشور النهائي أو كلمة SKIP:"""

        res = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=350)
        )
        return res.text.strip()
    except Exception as e:
        print(f"Gemini evaluation error: {e}")
        return None


def post_to_fb(message: str, image_url: str = None) -> bool:
    try:
        if image_url:
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
            data = {"url": image_url, "caption": message, "access_token": FACEBOOK_PAGE_TOKEN}
        else:
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
            data = {"message": message, "access_token": FACEBOOK_PAGE_TOKEN}
        r = requests.post(url, data=data, timeout=20).json()
        return "id" in r
    except:
        return False


# ===== محرك التعليقات المتواصل 24/7 =====
replied_comments_memory = set()

def comments_loop():
    while True:
        if SYSTEM_STATE["bot_enabled"] and FACEBOOK_PAGE_TOKEN:
            try:
                SYSTEM_STATE["last_comment_check"] = datetime.now().strftime("%I:%M:%S %p")
                url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
                res = requests.get(url, params={
                    "fields": "id,message,comments.limit(20).order(reverse_chronological){id,message,from,comments.limit(20).order(reverse_chronological){id,message,from}}",
                    "access_token": FACEBOOK_PAGE_TOKEN,
                    "limit": 5
                }, timeout=15).json()

                for post in res.get("data", []):
                    post_context = post.get("message", "")
                    comments_data = post.get("comments", {}).get("data", [])
                    for comment in comments_data:
                        cid = comment.get("id")
                        cmsg = comment.get("message", "").strip()
                        cauthor = comment.get("from", {}).get("name", "متابع")

                        # تجنب الرد على تعليقات الصفحة نفسها أو المكررة
                        if cid in replied_comments_memory or not cmsg or cauthor == PAGE_NAME:
                            continue

                        # توليد رد
                        reply_text = generate_reply(post_context, cmsg, cauthor)
                        if reply_text and "SKIP" not in reply_text:
                            # إرسال الرد
                            post_url = f"https://graph.facebook.com/v19.0/{cid}/comments"
                            requests.post(post_url, data={"message": reply_text, "access_token": FACEBOOK_PAGE_TOKEN}, timeout=10)
                            SYSTEM_STATE["comments_replied_count"] += 1
                        replied_comments_memory.add(cid)

            except Exception as e:
                print(f"Comments loop error: {e}")

        time.sleep(30)  # فحص كل 30 ثانية


def generate_reply(post_context, comment_text, author):
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        now_date = datetime.now().strftime("%Y-%m-%d")
        prompt = f"""أنت روبوت ذكي من مدينة الموصل تم برمجتك لصفحة "{PAGE_NAME}".
التاريخ اليوم: {now_date}. نحن في عام 2026.
المنشور: {post_context[:400]}
المعلق ({author}): "{comment_text}"
رد عليه بلهجة عراقية/مصلاوية مهذبة ومختصرة أو فصحى مبسطة. لا تتعدى سطرين. إذا إيموجي فارغ رد بـ SKIP."""
        res = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.8, max_output_tokens=256)
        )
        return res.text.strip()
    except:
        return None


# ===== محرك توقيت الأخبار (كل 3 ساعات) =====
def news_scheduler_loop():
    while True:
        check_and_post_curated_news()
        time.sleep(10800)  # كل 3 ساعات (10800 ثانية)


# تشغيل المحركات في الخلفية عند بدء التشغيل
threading.Thread(target=comments_loop, daemon=True).start()
threading.Thread(target=news_scheduler_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
