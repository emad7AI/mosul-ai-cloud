"""
===================================================
  الموصل AI - الخادم السحابي المتكامل 24/7 (Render Production v7)
  
  المعمارية المعزولة تماماً:
  1. وكيل التعليقات المستمر (Comments Engine):
     - Thread منفصل تماماً (فحص كل 25 ثانية).
     - رد ذكي، طبيعي، ومهذب باللهجة العراقية اللطيفة أو الفصحى المبسطة.
     - دعم كامل للمنشورات، الصور، والريلز والحوارات المتفرعة.
     - تدوير المفاتيح التلقائي لتجاوز أي حدود.
     
  2. وكيل الأخبار الذكي (News Engine):
     - Thread منفصل تماماً (فحص كل 15 دقيقة).
     - 3 قنوات معتمدة:
       * الصباح (@alsbaahiq): الموصل/الرواتب فوري | العام كل 3 ساعات.
       * جمال البدراني (@jamal_albadrany): العاجل فوري | العام كل 3 ساعات.
       * التكنولوجيا والذكاء الاصطناعي (@Axia_Tech): منشور كل 8 ساعات.
     - نصوص نقية فقط (Text-only) بدون أي صور أو علامات مائية.
     - صياغة تكيفية وذكية بدون انقطاع في النصوص ومعلومات دقيقة 100%.

  3. لوحة تحكم سحابية FastAPI ونقطة استيقاظ UptimeRobot.
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

# ===== إعدادات فيسبوك وجوجل =====
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "1322945474237295")
FACEBOOK_PAGE_TOKEN = os.getenv("FACEBOOK_PAGE_TOKEN", "")

# جلب مفاتيح جيميناي بأمان من متغيرات البيئة في Render
gemini_env = os.getenv("GEMINI_API_KEY", "")
if gemini_env:
    GEMINI_KEYS = [k.strip() for k in gemini_env.split(",") if k.strip()]
else:
    # محاولة القراءة من الإعدادات المحلية في حال التشغيل المحلي
    try:
        from config.settings import GEMINI_KEYS as LOCAL_KEYS, FACEBOOK_PAGE_TOKEN as LOCAL_FB_TOKEN
        GEMINI_KEYS = LOCAL_KEYS
        if not FACEBOOK_PAGE_TOKEN:
            FACEBOOK_PAGE_TOKEN = LOCAL_FB_TOKEN
    except Exception:
        GEMINI_KEYS = []

PAGE_NAME = "الموصل AI"
ACTIVE_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
KEY_PRIORITY = [7, 6, 5, 1, 0, 2, 3, 4]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ===== حالة النظام والإحصائيات =====
SYSTEM_STATE = {
    "comments_enabled": True,
    "news_enabled": True,
    "last_comment_check": "جاري البدء...",
    "comments_replied_count": 0,
    "last_news_check": "جاري البدء...",
    "news_published_count": 0,
    "last_news_title": "لا يوجد بعد",
    "last_action": "النظام يعمل بنجاح"
}

# ===== مسارات التخزين الدائم لمنع التكرار =====
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

REPLIED_FILE = os.path.join(DATA_DIR, "replied_comments.json")
PUBLISHED_NEWS_FILE = os.path.join(DATA_DIR, "published_news.json")
NEWS_TIMESTAMPS_FILE = os.path.join(DATA_DIR, "news_timestamps.json")


# -------------------------------------------------------------
# 1. إدارة ذاكرة التعليقات والأخبار
# -------------------------------------------------------------
def load_replied() -> set:
    if os.path.exists(REPLIED_FILE):
        try:
            with open(REPLIED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_replied(comment_id: str):
    replied = load_replied()
    replied.add(comment_id)
    try:
        with open(REPLIED_FILE, "w", encoding="utf-8") as f:
            json.dump(list(replied), f)
    except Exception as e:
        print(f"Error saving replied comments: {e}")

replied_memory = load_replied()

def load_published_news() -> set:
    if os.path.exists(PUBLISHED_NEWS_FILE):
        try:
            with open(PUBLISHED_NEWS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_published_news(post_id: str):
    news_set = load_published_news()
    news_set.add(post_id)
    try:
        with open(PUBLISHED_NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(news_set), f)
    except Exception as e:
        print(f"Error saving published news: {e}")

published_news_memory = load_published_news()

def load_timestamps() -> dict:
    if os.path.exists(NEWS_TIMESTAMPS_FILE):
        try:
            with open(NEWS_TIMESTAMPS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"last_any_post": 0, "last_alsabah": 0, "last_badrany": 0, "last_tech": 0}

def save_timestamps(ts: dict):
    try:
        with open(NEWS_TIMESTAMPS_FILE, "w", encoding="utf-8") as f:
            json.dump(ts, f, indent=2)
    except Exception as e:
        print(f"Error saving timestamps: {e}")


# -------------------------------------------------------------
# 2. وكيل التعليقات الذكي (Comments Engine)
# -------------------------------------------------------------
def get_posts_with_comments() -> list:
    items = []
    seen = set()

    for endpoint in ["feed", "published_posts"]:
        try:
            url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/{endpoint}"
            res = requests.get(url, params={
                "fields": "id,message,comments.limit(30){id,message,from,created_time,comments.limit(30){id,message,from,created_time}}",
                "access_token": FACEBOOK_PAGE_TOKEN,
                "limit": 25
            }, timeout=15).json()
            for p in res.get("data", []):
                pid = p.get("id")
                if pid and pid not in seen:
                    seen.add(pid)
                    items.append(p)
        except Exception:
            pass

    try:
        url_photos = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos"
        res_photos = requests.get(url_photos, params={
            "type": "uploaded",
            "fields": "id,name,comments.limit(30){id,message,from,created_time,comments.limit(30){id,message,from,created_time}}",
            "access_token": FACEBOOK_PAGE_TOKEN,
            "limit": 25
        }, timeout=15).json()
        for p in res_photos.get("data", []):
            pid = p.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                items.append(p)
    except Exception:
        pass

    try:
        url_reels = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/video_reels"
        res_reels = requests.get(url_reels, params={
            "fields": "id,description,comments.limit(30){id,message,from,created_time,comments.limit(30){id,message,from,created_time}}",
            "access_token": FACEBOOK_PAGE_TOKEN,
            "limit": 20
        }, timeout=15).json()
        for p in res_reels.get("data", []):
            pid = p.get("id")
            if pid and pid not in seen:
                seen.add(pid)
                items.append(p)
    except Exception:
        pass

    return items


def generate_smart_reply(context_text: str, comment_text: str, author: str) -> str | None:
    current_date = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""أنت مساعد ذكي ولطيف يدير صفحة "{PAGE_NAME}" على فيسبوك.
التاريخ الحالي اليوم هو: {current_date}. نحن الآن في عام 2026.
تذكر دائماً أننا في عام 2026! أجب بناءً على أحدث التطورات ولا تقل أبداً أننا لم نصل لهذا العام.

السياق (سواء كان المنشور أو بداية الحوار):
---
{context_text[:800] if context_text else "منشور عام لصفحة الموصل AI"}
---

الآن، المستخدم ({author}) كتب لك هذا التعليق:
"{comment_text}"

مهمتك:
- اقرأ التعليق وافهم هل هو تعليق جديد أم رد على كلامك السابق؟ ورد بناءً على ذلك.
- أجب بمعلومات مواكبة لزمننا الحالي (2026).
- إذا كان يطرح سؤالاً أو استفساراً، أجب عليه بذكاء وبطريقة واضحة ومفيدة تخدمه.
- إذا كان يعبّر عن رأي، ناقشه بود واحترام.
- إذا كان يشكرك، اشكره وقل أنك في الخدمة دائماً.
- إذا كان تفاعلاً بسيطاً أو دعاءً (مثل: ياساتر، الله يستر، بالتوفيق، عاشت ايديكم، روعة، وردة)، رد عليه بلطف وبدعاء طيب يتناسب مع سياق المنشور.
- اكتب بالعربية الفصحى المبسطة أو العامية العراقية اللطيفة جداً والمهذبة (أسلوب طبيعي ومريح بدون أي تصنع أو تكلف).
- لا تبدأ بـ "بالتأكيد" أو عبارات روبوتية جافة.
- لا تستخدم أكثر من إيموجي واحد أو اثنين.
- إذا كان التعليق مسيئاً تماماً (سباب أو شتيمة)، أرجع الكلمة: SKIP

الرد:"""

    ordered_keys = [GEMINI_KEYS[i] for i in KEY_PRIORITY if i < len(GEMINI_KEYS)]

    for key in ordered_keys:
        client = genai.Client(api_key=key)
        for model in ACTIVE_MODELS:
            try:
                chat = client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        temperature=0.7,
                        max_output_tokens=600,
                    )
                )
                response = chat.send_message(prompt)
                if response and response.text:
                    reply = response.text.strip()
                    if "SKIP" in reply or len(reply) < 3:
                        return None
                    return reply
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    break
                continue

    return None


def post_reply(comment_id: str, reply_text: str) -> bool:
    url = f"https://graph.facebook.com/v19.0/{comment_id}/comments"
    try:
        res = requests.post(url, data={
            "message": reply_text,
            "access_token": FACEBOOK_PAGE_TOKEN
        }, timeout=15).json()

        if "id" in res:
            print(f"  ✅ تم الرد بنجاح على التعليق [{comment_id}]")
            return True
        else:
            print(f"  ❌ فشل الرد: {res.get('error', {}).get('message', 'خطأ غير معروف')}")
            return False
    except Exception as e:
        print(f"  ❌ خطأ في إرسال الرد: {e}")
        return False


def monitor_and_reply_cycle():
    if not SYSTEM_STATE["comments_enabled"]:
        return

    now_str = datetime.now().strftime("%I:%M:%S %p")
    SYSTEM_STATE["last_comment_check"] = now_str

    posts = get_posts_with_comments()
    if not posts:
        return

    new_replies = 0

    def process_single_comment(c_data, context_text):
        nonlocal new_replies
        c_id = c_data.get("id", "")
        c_text = c_data.get("message", "").strip()
        c_author = c_data.get("from", {}).get("name", "متابع")
        c_author_id = str(c_data.get("from", {}).get("id", ""))

        if len(c_text) < 2:
            return
        if c_author_id == str(FACEBOOK_PAGE_ID) or PAGE_NAME in c_author:
            return
        if c_id in replied_memory:
            return

        print(f"  💬 تعليق جديد من [{c_author}]: {c_text[:70]}")
        reply = generate_smart_reply(context_text, c_text, c_author)
        if reply:
            if post_reply(c_id, reply):
                save_replied(c_id)
                replied_memory.add(c_id)
                new_replies += 1
                SYSTEM_STATE["comments_replied_count"] += 1
                time.sleep(2)
        else:
            save_replied(c_id)
            replied_memory.add(c_id)

    for post in posts:
        post_text = post.get("message") or post.get("description") or post.get("title") or post.get("name") or ""
        top_comments = post.get("comments", {}).get("data", [])

        for t_comment in top_comments:
            t_id = t_comment.get("id", "")
            nested_comments = t_comment.get("comments", {}).get("data", [])

            already_replied_fb = any(
                str(r.get("from", {}).get("id", "")) == str(FACEBOOK_PAGE_ID)
                or PAGE_NAME in (r.get("from", {}).get("name") or "")
                for r in nested_comments
            )

            if t_id not in replied_memory:
                if already_replied_fb:
                    save_replied(t_id)
                    replied_memory.add(t_id)
                else:
                    process_single_comment(t_comment, post_text)

            for n_comment in nested_comments:
                if n_comment.get("id", "") not in replied_memory:
                    full_context = f"المنشور:\n{post_text}\n\nسياق الحوار الأولي:\n{t_comment.get('message', '')}"
                    process_single_comment(n_comment, full_context)

    if new_replies > 0:
        print(f"  🎯 تم الرد على ({new_replies}) تعليقات بنجاح!")
        SYSTEM_STATE["last_action"] = f"تم الرد على {new_replies} تعليق في {now_str}"


# -------------------------------------------------------------
# 3. وكيل الأخبار الذكي (News Engine)
# -------------------------------------------------------------
MOSUL_KEYWORDS = [
    "الموصل", "نينوى", "الحدباء", "تلعفر", "سنجار", "مخمور", "حمام العليل",
    "الحمدانية", "بعشيقة", "مطار الموصل", "جامعة الموصل", "محافظ نينوى", "سد الموصل"
]
SALARY_KEYWORDS = [
    "رواتب", "راتب", "سلم الرواتب", "صرف الرواتب", "صرف رواتب", "تمويل رواتب",
    "تعيينات", "درجات وظيفية", "عقود", "الموازنة"
]
BADRANY_URGENT_KEYWORDS = [
    "عاجل", "عاجـل", "هام", "قرار", "المرور", "عطلة", "طوارئ",
    "صحة نينوى", "شرطة نينوى", "توجيه رسمي", "مجلس الوزراء"
]

def fetch_telegram_messages(channel_handle: str) -> list:
    url = f"https://t.me/s/{channel_handle}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            return []
        
        soup = BeautifulSoup(res.text, "html.parser")
        msg_divs = soup.find_all("div", class_="tgme_widget_message")
        
        results = []
        for div in msg_divs:
            post_id = div.get("data-post")
            if not post_id:
                continue
            
            text_elem = div.find("div", class_="tgme_widget_message_text")
            if not text_elem:
                continue
            
            raw_text = text_elem.get_text(separator="\n").strip()
            if len(raw_text) < 30:
                continue
            
            results.append({"id": post_id, "text": raw_text})
        return results
    except Exception as e:
        print(f"  ⚠️ خطأ في قراءة @{channel_handle}: {e}")
        return []

def classify_news_item(channel: str, text: str) -> tuple[bool, bool]:
    text_lower = text.lower()
    
    if channel == "alsbaahiq":
        is_mosul = any(k in text for k in MOSUL_KEYWORDS)
        is_salary = any(k in text for k in SALARY_KEYWORDS)
        if is_mosul or is_salary:
            return True, True
        iraq_general = any(k in text for k in ["العراق", "مجلس الوزراء", "السوداني", "وزارة", "المرور", "الكهرباء"])
        if iraq_general:
            return True, False
        return False, False
        
    elif channel == "jamal_albadrany":
        is_urgent = any(k in text for k in BADRANY_URGENT_KEYWORDS)
        is_mosul = any(k in text for k in MOSUL_KEYWORDS)
        if is_urgent or is_mosul:
            return True, True
        if any(k in text for k in ["تنويه", "المواطنين", "وزارة", "الخدمات"]):
            return True, False
        return False, False
        
    elif channel == "Axia_Tech":
        tech_words = ["ذكاء اصطناعي", "تطبيق", "تحديث", "أبل", "جوجل", "سامسونج", "chatgpt", "gemini", "هاتف", "ميزة", "تقنية", "ai"]
        if any(w in text_lower for w in tech_words):
            return True, False
        return False, False

    return False, False

def rewrite_news_adaptive(channel: str, raw_text: str) -> str | None:
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    channel_context = {
        "alsbaahiq": "مصدر رسمي عراقي",
        "jamal_albadrany": "أخبار محلية عاجلة وخدمية للمواطنين",
        "Axia_Tech": "أخبار تكنولوجيا وذكاء اصطناعي تفيد الناس"
    }.get(channel, "أخبار عامة")

    prompt = f"""أنت رئيس تحرير صحفي ذكي ومحترف لصفحة فيسبوك رسمية تسمى "{PAGE_NAME}".
التاريخ الحالي: {current_date} (عام 2026).
نوع المحتوى: {channel_context}.

الخبر الخام:
\"\"\"
{raw_text}
\"\"\"

التعليمات التحريرية الصارمة:
1. الأمانة والدقة المطلقة: ممنوع اختلاق أو تخمين أي معلومة. الأرقام، التواريخ، والوقائع يجب أن تطابق الأصل 100%.
2. المرونة والذكاء التحريري في الطول:
   - إذا كان الخبر خبراً سريعاً أو قراراً مباشراً (مثل تمديد مهلة، عطلة، تبليغ، تصريح سريع)، صِغه في سطر واحد أو سطرين مكثفين ومباشرين.
   - إذا كان الخبر يحمل قائمة قرارات طويلة (مثل جلسة حكومية)، لا تسرد كل البنود؛ اختر أهم 3 إلى 4 قرارات تهم المواطن والشارع مباشرة ولخصها بنقاط واضحة.
3. اكتمال النص وسلامة النهاية: احرص تماماً على أن يكون المنشور مكتملاً حتى آخر كلمة، وممنوع منعاً باتاً أن تكون الجملة الأخيرة ناقصة أو مقطوعة.
4. احذف تماماً أي ذكر لأسماء القنوات الأصلية (مثل: الصباح، البدراني، تيليجرام)، واحذف الروابط والمعرفات الخارجية.
5. ابدأ بإيموجي صحفي رسمي مناسب (مثل 🚨، 📢، 💡، 🏗️).
6. اختم بسؤال تفاعلي ذكي ومحفز للجمهور للتعليق وإبداء الرأي.
7. اختم بهاشتاغات الصفحة:
#الموصل_AI #الموصل #نينوى #العراق

أرجع نص المنشور الجاهز للنشر فقط:"""

    ordered_keys = [GEMINI_KEYS[i] for i in KEY_PRIORITY if i < len(GEMINI_KEYS)]
    
    for key in ordered_keys:
        client = genai.Client(api_key=key)
        for model in ACTIVE_MODELS:
            try:
                chat = client.chats.create(
                    model=model,
                    config=types.GenerateContentConfig(
                        temperature=0.3,
                        max_output_tokens=1000
                    )
                )
                response = chat.send_message(prompt)
                if response and response.text:
                    out = response.text.strip()
                    if len(out) > 20 and "#" in out and "SKIP" not in out:
                        return out
            except Exception as e:
                err = str(e)
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    break
                continue
                
    return None

def publish_news_to_facebook(text: str) -> bool:
    url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed"
    try:
        res = requests.post(url, data={
            "message": text,
            "access_token": FACEBOOK_PAGE_TOKEN
        }, timeout=20).json()
        
        if "id" in res:
            print(f"  ✅ تم نشر الخبر بنجاح على فيسبوك! (Post ID: {res['id']})")
            return True
        else:
            err = res.get("error", {}).get("message", "خطأ غير معروف")
            print(f"  ❌ فشل نشر الخبر على فيسبوك: {err}")
            return False
    except Exception as e:
        print(f"  ❌ خطأ في الاتصال بفيسبوك: {e}")
        return False

def check_and_publish_news_cycle():
    if not SYSTEM_STATE["news_enabled"]:
        return False

    now_str = datetime.now().strftime("%I:%M:%S %p")
    SYSTEM_STATE["last_news_check"] = now_str
    now = time.time()
    ts = load_timestamps()
    published_ids = load_published_news()

    MIN_GLOBAL_INTERVAL = 25 * 60
    if (now - ts.get("last_any_post", 0)) < MIN_GLOBAL_INTERVAL:
        return False

    channels_to_check = [
        {"name": "alsbaahiq",       "min_interval": 3 * 3600, "ts_key": "last_alsabah"},
        {"name": "jamal_albadrany", "min_interval": 3 * 3600, "ts_key": "last_badrany"},
        {"name": "Axia_Tech",       "min_interval": 8 * 3600, "ts_key": "last_tech"},
    ]

    for ch_info in channels_to_check:
        ch_name = ch_info["name"]
        ts_key = ch_info["ts_key"]
        min_interval = ch_info["min_interval"]
        last_post_time = ts.get(ts_key, 0)
        time_since_last = now - last_post_time

        messages = fetch_telegram_messages(ch_name)
        if not messages:
            continue

        unseen = [m for m in messages if m["id"] not in published_ids]
        if not unseen:
            continue

        candidate = None
        for item in reversed(unseen):
            eligible, urgent = classify_news_item(ch_name, item["text"])
            if not eligible:
                continue

            if urgent or time_since_last >= min_interval:
                candidate = item
                break

        if candidate:
            print(f"\n📢 خبر جديد مؤهل من @{ch_name} | ID: {candidate['id']}")
            formatted = rewrite_news_adaptive(ch_name, candidate["text"])
            if not formatted:
                save_published_news(candidate["id"])
                continue

            if publish_news_to_facebook(formatted):
                save_published_news(candidate["id"])
                published_news_memory.add(candidate["id"])
                ts["last_any_post"] = now
                ts[ts_key] = now
                save_timestamps(ts)
                
                SYSTEM_STATE["news_published_count"] += 1
                SYSTEM_STATE["last_news_title"] = formatted.split("\n")[0][:45]
                SYSTEM_STATE["last_action"] = f"تم نشر خبر جديد من @{ch_name} في {now_str}"
                return True
            else:
                save_published_news(candidate["id"])
                return False

    return False


# -------------------------------------------------------------
# 4. المعمارية المعزولة تماماً (Background Workers)
# -------------------------------------------------------------
def comments_worker():
    print("🚀 بدء تشغيل خادم التعليقات المستمر (Thread 1) 24/7...")
    while True:
        try:
            monitor_and_reply_cycle()
        except Exception as e:
            print(f"⚠️ خطأ غير متوقع في خادم التعليقات: {e}")
        time.sleep(25)

def news_worker():
    print("🚀 بدء تشغيل خادم الأخبار المستقل (Thread 2) كل 15 دقيقة...")
    while True:
        try:
            check_and_publish_news_cycle()
        except Exception as e:
            print(f"⚠️ خطأ غير متوقع في خادم الأخبار: {e}")
        time.sleep(900)  # فحص كل 15 دقيقة


# -------------------------------------------------------------
# 5. تطبيق الويب ولوحة التحكم (FastAPI)
# -------------------------------------------------------------
if HAS_FASTAPI:
    app = FastAPI(title="الموصل AI - خادم سحابي متكامل 24/7")

    @app.on_event("startup")
    def startup_event():
        # تشغيل الوكيلين في خيطين منفصلين تماماً
        t_comments = threading.Thread(target=comments_worker, daemon=True)
        t_comments.start()
        
        t_news = threading.Thread(target=news_worker, daemon=True)
        t_news.start()

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        comments_status = "🟢 شغال ويفحص كل 25 ثانية" if SYSTEM_STATE["comments_enabled"] else "🔴 متوقف مؤقتاً"
        news_status = "🟢 شغال ويفحص القنوات الـ 3 كل 15 دقيقة" if SYSTEM_STATE["news_enabled"] else "🔴 متوقف مؤقتاً"

        toggle_c_btn = "إيقاف التعليقات ⏸️" if SYSTEM_STATE["comments_enabled"] else "تشغيل التعليقات ▶️"
        toggle_n_btn = "إيقاف الأخبار ⏸️" if SYSTEM_STATE["news_enabled"] else "تشغيل الأخبار ▶️"

        html = f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>الموصل AI - مركز التحكم السحابي 24/7</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b1329; color: #f8fafc; text-align: center; padding: 20px; }}
        .card {{ background: #162447; border-radius: 20px; padding: 25px; max-width: 520px; margin: 15px auto; box-shadow: 0 10px 35px rgba(0,0,0,0.5); border: 1px solid #1f3a60; }}
        h1 {{ color: #00d2ff; font-size: 24px; margin-bottom: 4px; }}
        .section {{ background: #1f3158; border-radius: 14px; padding: 15px; margin: 15px 0; text-align: right; border: 1px solid #2a4365; }}
        .section-title {{ font-weight: bold; font-size: 16px; color: #00d2ff; margin-bottom: 8px; }}
        .btn {{ display: inline-block; width: 47%; padding: 12px; margin: 5px 1%; border: none; border-radius: 10px; font-size: 14px; font-weight: bold; cursor: pointer; text-decoration: none; box-sizing: border-box; }}
        .btn-action {{ background: #2ec4b6; color: #0b1329; }}
        .btn-toggle {{ background: #0077b6; color: white; }}
        .stats {{ font-size: 13px; color: #cbd5e1; line-height: 2; margin-top: 5px; }}
        .badge {{ padding: 3px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🌐 الموصل AI - الخادم السحابي المستقل</h1>
        <p style="color:#94a3b8;font-size:13px;margin-top:0;">وكيل التعليقات + وكيل الأخبار (عزل تام 100%)</p>
        
        <!-- قسم التعليقات -->
        <div class="section">
            <div class="section-title">💬 وكيل التعليقات الذكي</div>
            <div class="stats">
                <div>الحالة: <b>{comments_status}</b></div>
                <div>آخر فحص: <b>{SYSTEM_STATE["last_comment_check"]}</b></div>
                <div>إجمالي الردود: <b style="color:#00ff88;">{SYSTEM_STATE["comments_replied_count"]}</b></div>
            </div>
            <div style="margin-top:10px;">
                <a href="/trigger-comments" class="btn btn-action">فحص التعليقات الآن</a>
                <a href="/toggle-comments" class="btn btn-toggle">{toggle_c_btn}</a>
            </div>
        </div>

        <!-- قسم الأخبار -->
        <div class="section">
            <div class="section-title">📰 وكيل الأخبار التلقائي (3 قنوات)</div>
            <div class="stats">
                <div>الحالة: <b>{news_status}</b></div>
                <div>القنوات: <b>الصباح | جمال البدراني | التكنولوجيا</b></div>
                <div>آخر فحص: <b>{SYSTEM_STATE["last_news_check"]}</b></div>
                <div>إجمالي المنشورات: <b style="color:#00ff88;">{SYSTEM_STATE["news_published_count"]}</b></div>
                <div>آخر خبر: <i>{SYSTEM_STATE["last_news_title"]}</i></div>
            </div>
            <div style="margin-top:10px;">
                <a href="/trigger-news" class="btn btn-action">فحص الأخبار الآن</a>
                <a href="/toggle-news" class="btn btn-toggle">{toggle_n_btn}</a>
            </div>
        </div>

        <div style="color:#64748b;font-size:12px;margin-top:15px;">
            آخر إجراء للنظام: {SYSTEM_STATE["last_action"]}
        </div>
    </div>
</body>
</html>"""
        return html

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "time": datetime.now().isoformat(),
            "comments_count": SYSTEM_STATE["comments_replied_count"],
            "news_count": SYSTEM_STATE["news_published_count"]
        }

    @app.get("/toggle-comments")
    def toggle_comments():
        SYSTEM_STATE["comments_enabled"] = not SYSTEM_STATE["comments_enabled"]
        return HTMLResponse("<script>window.location.href='/';</script>")

    @app.get("/toggle-news")
    def toggle_news():
        SYSTEM_STATE["news_enabled"] = not SYSTEM_STATE["news_enabled"]
        return HTMLResponse("<script>window.location.href='/';</script>")

    @app.get("/trigger-comments")
    def trigger_comments():
        threading.Thread(target=monitor_and_reply_cycle).start()
        return HTMLResponse("<script>alert('تم إطلاق فحص التعليقات فوراً في الخلفية!'); window.location.href='/';</script>")

    @app.get("/trigger-news")
    def trigger_news():
        threading.Thread(target=check_and_publish_news_cycle).start()
        return HTMLResponse("<script>alert('تم إطلاق فحص الأخبار فوراً في الخلفية!'); window.location.href='/';</script>")

else:
    app = None

if __name__ == "__main__":
    if HAS_FASTAPI:
        port = int(os.getenv("PORT", 10000))
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        # تشغيل محلي بدون سيرفر ويب
        t1 = threading.Thread(target=comments_worker, daemon=True)
        t1.start()
        t2 = threading.Thread(target=news_worker, daemon=True)
        t2.start()
        while True:
            time.sleep(1)
