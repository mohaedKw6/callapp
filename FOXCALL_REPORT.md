# تقرير مشروع FOXCALL — الحالة الكاملة

> آخر تحديث: 23 أبريل 2026

---

## 1) ملخص تنفيذي (الإجابة المباشرة)

**هل التطبيق دلوقتي بيعمل مكالمة live بصوت بين الطرفين؟ — لأ.**

تم إصلاح كل أخطاء الواجهة (التوكن بقى يتفك، التطبيق يفتح بدون كراش، شاشة الـ Numpad شغّالة، الرصيد بيظهر، طلب المكالمة بيتسجّل في السيرفر)، **لكن الصوت الحقيقي بين الطرفين لا يعمل** في النسخة دي وده مش هيتحل بإصلاح بسيط — الموضوع معماري (architectural) هتفاصيل تحت في قسم "العائق التقني الأساسي".

النسخة الوحيدة اللي بتعمل صوت حقيقي هي `FOXCALL.apk` الأصلي (75 ميجا، مكتوب بـ Kotlin + Linphone).

---

## 2) الهيكل العام للمشروع

```
workspace/
├── bot/                          # بوت تيليجرام (Python + Flask)
│   ├── bot.py                    # نقطة التشغيل الرئيسية
│   ├── callv2.py                 # منطق المكالمات + Telicall integration
│   ├── foxapp_api.py             # Flask API على بورت 5000 (للتطبيق)
│   ├── users_db.json             # قاعدة بيانات المستخدمين والأرصدة
│   ├── bot_data.json             # إعدادات البوت
│   └── tokens_cache.json         # كاش توكنز Telicall
│
├── fox-call/                     # تطبيق React Native (Expo SDK 54)
│   ├── App.tsx                   # الواجهة الرئيسية (إدخال توكن + Numpad)
│   ├── services/
│   │   ├── foxToken.ts           # فك تشفير توكن البوت (SHA256/HMAC inline)
│   │   ├── telicall.ts           # عميل HTTP للـ Bot API
│   │   └── sip.ts                # مدير المكالمة (signaling-only، بدون صوت)
│   ├── components/Numpad.tsx
│   ├── app.json                  # إعدادات Expo (project ID, package name, perms)
│   └── eas.json                  # إعدادات EAS Build
│
├── artifacts/api-server/         # Express API server (proxy للـ bot)
│   └── src/routes/botProxy.ts    # /api/bot/* → http://127.0.0.1:5000/*
│
└── artifacts/mockup-sandbox/     # غير مستخدم في الإنتاج
```

---

## 3) المسار الكامل للمكالمة (How It Works)

```
المستخدم في تيليجرام
        │
        ▼
┌──────────────────┐  /token        ┌──────────────────┐
│  Fox Bot         │ ─────────────▶│  encode_token()  │
│  (bot.py)        │                │  user_id|url|... │
└──────────────────┘                └────────┬─────────┘
                                             │
                          توكن مشفّر بـ XOR + HMAC-SHA256
                                             │
                                             ▼
                                ┌─────────────────────┐
                                │ المستخدم يدخل التوكن│
                                │ في تطبيق fox-call    │
                                └──────────┬──────────┘
                                           │ decodeFoxToken()
                                           ▼
                              يستخرج: userId + serverUrl
                                           │
                                           ▼
                          GET /api/me  →  الاسم + الرصيد
                                           │
                          POST /api/call/start { to: "+201..." }
                                           │
                                           ▼
                   البوت يستدعي Telicall API ويرجع بيانات SIP:
                   {
                     domain: "sip-uk-1.getcontact.com",
                     port: 5061,
                     protocol: "tls",
                     username, password, callLimit
                   }
                                           │
                                           ▼
                  ┌────────────────────────────────────────┐
                  │  هنا اللي بنحتاجه:                      │
                  │  Linphone/PJSIP يفتح TLS socket        │
                  │  لـ sip-uk-1.getcontact.com:5061       │
                  │  ويبدأ RTP بين الطرفين                  │
                  └────────────────────────────────────────┘
                                           │
                  ❌ مفيش تطبيق React Native يقدر يعمل ده
                  ✅ FOXCALL.apk الأصلي (Linphone) يعمل ده
```

---

## 4) ما تم إنجازه ✅

### 4.1 إعدادات وأسرار
- إعداد كل الـ secrets المطلوبة:
  - `BOT_TOKEN` (تيليجرام)
  - `GITHUB_TOKEN` (للوصول لـ repo `MohamedQM/FOXCALL-` الخاص)
  - `EXPO_TOKEN` (للبناء على EAS)
  - `SESSION_SECRET`
- البوت بيشتغل على بورت 5000، الـ API server على 8080.

### 4.2 إصلاح أخطاء التطبيق
- **خطأ "undefined is not a function"** عند إدخال التوكن: تم إصلاحه عن طريق:
  - حذف مكتبة `js-sha256` (مش متوافقة مع React Native Hermes)
  - حذف مكتبة `jssip` (كانت بتتحمّل modules غير موجودة في RN)
  - كتابة SHA256 + HMAC-SHA256 + Base64URL + UTF-8 من الصفر داخل `foxToken.ts` (~200 سطر pure JS، بدون أي dependency خارجي)
  - تم اختبار الكود محلياً مع التوكن الحقيقي وفعلاً بيفك التشفير صح ويستخرج `userId` و `serverUrl`

### 4.3 الواجهة (UI)
- شاشة إدخال التوكن
- شاشة عرض الاسم والرصيد بعد الاتصال
- Numpad كامل (أرقام + * # + delete)
- شاشة المكالمة (عرض الرقم + زر قطع)
- كل النصوص بالعربي
- تخزين التوكن في Secure Store

### 4.4 ربط التطبيق بالسيرفر
- `telicall.ts`: عميل HTTP يستدعي `/api/me` و `/api/balance` و `/api/call/start` و `/api/call/end`
- `sip.ts`: signaling-only — بيرسل طلب المكالمة للسيرفر، السيرفر يسجّلها ويخصم من الرصيد، التطبيق يعرض UI ringing → connected → ended
- API server (Express) يعمل proxy لـ `/api/bot/*` → bot Flask على بورت 5000

### 4.5 بناء EAS
- تم إعداد المشروع على Expo بحساب `moha1122am`
- Project ID: `5c6e8fde-f9c7-4611-a61c-67cec76d3b2d`
- Package name: `com.mohamedqm.foxcall`
- Build حالي قيد التنفيذ:
  https://expo.dev/accounts/moha1122am/projects/fox-call/builds/34388261-98b3-450e-afd6-8109758d35dc

---

## 5) العائق التقني الأساسي ⚠️ (لماذا الصوت لا يعمل)

### الحقيقة من فحص السيرفر:
```bash
$ POST /api/call/start
{
  "sip": {
    "domain": "sip-uk-1.getcontact.com",
    "port": 5061,
    "protocol": "tls",      ◀── هنا المشكلة
    ...
  }
}
```

السيرفر يتحدث **TLS-SIP** (SIP over TLS على TCP). هذا البروتوكول:

| التقنية | يدعم TLS-SIP؟ | السبب |
|---|---|---|
| Linphone (في APK الأصلي) | ✅ | C/C++ يفتح TCP socket بحرية |
| Native PJSIP | ✅ | C library |
| **JsSIP في المتصفح/RN** | ❌ | يدعم WSS فقط (WebSocket Secure) |
| **react-native-webrtc** | ❌ | للـ media فقط، لا يفتح SIP socket |
| **أي حل JavaScript خالص** | ❌ | مستحيل — لا يوجد TCP API في JS |

### الحلول الممكنة (مرتبة حسب الصعوبة):

#### الخيار 1️⃣ — استخدم APK الأصلي (الموصى به الآن)
- موجود في `MohamedQM/FOXCALL-` على GitHub
- يشتغل بصوت كامل
- **هذا هو الحل الوحيد المتاح فوراً**

#### الخيار 2️⃣ — أضف WSS Gateway أمام السيرفر
- ضع `Kamailio` أو `OpenSIPS` بين الموبايل وسيرفر Telicall
- الموبايل يتصل بـ WSS → الـ gateway يحول إلى TLS TCP
- يحتاج VPS + إعداد Kamailio (~20-40 ساعة عمل)
- بعدها يمكن استخدام JsSIP + react-native-webrtc

#### الخيار 3️⃣ — Custom Native Module في Expo
- اعمل `expo-config-plugin` يضيف Linphone SDK Android
- أو ابحث عن `react-native-pjsip` fork حديث
- المشكلة: كل forks الموجودة قديمة (آخرها لـ RN 0.65) ومش متوافقة مع SDK 54
- يحتاج كتابة wrapper من الصفر (~80-160 ساعة عمل)

#### الخيار 4️⃣ — Kotlin Native App (نفس النهج الأصلي)
- ابدأ من `FOXCALL.apk` الأصلي، حدّث الواجهة فقط
- هذا أقصر طريق لتطبيق native كامل

---

## 6) قائمة المشاكل (Issues Backlog)

### 🔴 حرج (Critical)
- **[BLOCKER]** الصوت لا يعمل في `fox-call/` — يحتاج قرار معماري (راجع قسم 5)
- المكالمة في النسخة الحالية signaling-only (تُحسب على الرصيد لكن بدون صوت) — قد يربك المستخدم

### 🟡 متوسط
- توكن EXPO الجديد (`9TncHLfraZx1k3vpFUV0amK-WFA87-Qc5eQiKqXo`) غير محفوظ في Secrets — يحتاج تحديث لـ `EXPO_TOKEN`
- لا يوجد deeplink للتطبيق (المستخدم لازم ينسخ التوكن يدوياً من تيليجرام)
- لا يوجد إشعارات (notifications) للمكالمات الواردة
- Build على EAS Free محدود (30 build/شهر) — قد ينفد بسرعة عند التجارب

### 🟢 تحسينات مستقبلية
- إضافة سجل المكالمات (call history) داخل التطبيق
- شاشة رصيد منفصلة مع تاريخ العمليات
- Dark mode toggle
- دعم لغات إضافية
- اختصارات للأرقام المفضلة

---

## 7) كيفية رفع التغييرات لـ GitHub

⚠️ **ملاحظة:** الـ Agent ما يقدرش يعمل push مباشرة من بيئة Replit (git operations محظورة). فيه طريقتين:

### الطريقة الأولى: من واجهة Replit
1. افتح تاب **Version Control** على الشمال (أيقونة git)
2. اعمل **Connect to GitHub**
3. اختار repo: `MohamedQM/FOXCALL-`
4. اعمل **Commit & Push** للتغييرات الحالية

### الطريقة الثانية: من الـ Shell
```bash
# تأكد إن GITHUB_TOKEN موجود في Secrets
git config user.name "MohamedQM"
git config user.email "your@email.com"
git remote set-url origin https://${GITHUB_TOKEN}@github.com/MohamedQM/FOXCALL-.git
git add .
git commit -m "Fix token decoding, remove jssip, add EAS build"
git push origin main
```

---

## 8) الأسرار والتوكنز (Secrets Management)

### الموجودة حالياً في Replit Secrets:
| الاسم | الاستخدام |
|---|---|
| `BOT_TOKEN` | توكن بوت تيليجرام |
| `GITHUB_TOKEN` | الوصول لـ private repo |
| `EXPO_TOKEN` | بناء APK على EAS *(يحتاج تحديث للتوكن الجديد)* |
| `SESSION_SECRET` | جلسات Flask |

### القيم الجديدة المطلوب حفظها:
- **`EXPO_TOKEN` الجديد:** `9TncHLfraZx1k3vpFUV0amK-WFA87-Qc5eQiKqXo`
  - افتح Secrets pane في Replit
  - عدّل قيمة `EXPO_TOKEN` للقيمة الجديدة دي
  - بعدها كل أوامر EAS هتشتغل بالحساب الجديد تلقائياً

### مكان حفظ كل توكن:
- توكنز Telegram users → `bot/users_db.json`
- توكنز Telicall (السيرفر الخارجي) → `bot/tokens_cache.json`
- توكنز التطبيق (Fox tokens) → تتولّد عند الطلب من `bot/foxapp_api.py:encode_token()` ولا تُخزن

---

## 9) كيفية النشر (Deployment)

### النشر للبوت + API Server (Replit Deployment):
1. اضغط زرار **Publish** أعلى يمين Replit
2. اختار **Reserved VM** (للـ background worker زي البوت)
3. الـ deployment هيشغّل تلقائياً:
   - `bot/bot.py` (البوت + Flask API على 5000)
   - `artifacts/api-server` (Express proxy على 8080)
4. هتاخد domain شكله: `foxcall-bot.replit.app`
5. **مهم:** بعد النشر، حدّث `PUBLIC_URL` في الـ secrets ليطابق الـ domain الجديد، عشان التوكنز اللي البوت يصدرها تشاور للسيرفر الإنتاجي مش للـ dev domain.

### النشر للـ APK (EAS Build):
- Build بيتعمل تلقائياً عن طريق EAS
- بعد ما يخلص، رابط التحميل بيظهر في:
  https://expo.dev/accounts/moha1122am/projects/fox-call/builds
- المستخدمين بيفتحوا الرابط من الموبايل وبيحملوا APK مباشرة
- لو عايز توزيع أوسع (Play Store) لازم تستبدل profile `preview` بـ `production` في `eas.json` وتعمل submit لـ Play Console

---

## 10) معماريات بديلة محتملة (للنقاش)

### A) WSS Gateway Architecture (موصى به للحفاظ على fox-call/)
```
Mobile (RN + JsSIP + react-native-webrtc)
        ↓ WSS
Kamailio Gateway (VPS)
        ↓ TLS-SIP
sip-uk-1.getcontact.com:5061
```
**المزايا:** يحافظ على استخدام Expo + JS، نفس واجهة التطبيق الحالية تشتغل  
**العيوب:** يحتاج VPS + خبرة Kamailio + تكلفة شهرية

### B) Hybrid: Expo UI + Native Linphone Module
```
Expo App (UI)
   ↓ JSI bridge
Native module (Java/Kotlin) يحتوي Linphone SDK
   ↓ TLS-SIP
sip-uk-1.getcontact.com:5061
```
**المزايا:** UI سهل التحديث (JS)، صوت حقيقي  
**العيوب:** صعب جداً، يحتاج كتابة custom module + اختبار، الـ APK يكبر لـ 50+ MB

### C) Pure Native (الموجود حالياً في FOXCALL.apk)
```
Kotlin App (UI + Linphone مباشرة)
   ↓ TLS-SIP
sip-uk-1.getcontact.com:5061
```
**المزايا:** الأبسط، يعمل الآن  
**العيوب:** UI محتاج Kotlin مش JS، تطوير أبطأ

---

## 11) أفكار وتوصيات

1. **القرار العاجل:** قبل أي تطوير إضافي، خد قرار: نلتزم بـ React Native (مع Gateway) ولا نرجع لـ Kotlin Native؟
2. **اختبر الـ APK الجديد** اللي بنبنيه دلوقتي بصراحة كاملة — اعرف المستخدم إنه UI فقط، الصوت في النسخة الأصلية.
3. **افصل Bot Server عن Production:** خلي الـ dev يستخدم dev domain، والـ APK المنشور يستخدم production domain ثابت.
4. **اعمل rate limiting** على `/api/call/start` عشان متعرضش السيرفر للإساءة لو APK تسرّب.
5. **Health check:** ضيف endpoint `/api/health` يرجّع حالة الاتصال بـ Telicall — يساعد في التشخيص.

---

## 12) خلاصة الإجابة على سؤالك

> **"هل التطبيق دلوقتي يقدر يعمل مكالمة بين الطرفين بدون مشاكل؟"**

**لأ.** 

التطبيق دلوقتي:
- ✅ بيفتح بدون أخطاء
- ✅ بيقبل التوكن ويفكه صح
- ✅ بيعرض الاسم والرصيد
- ✅ بيرسل طلب المكالمة للسيرفر (السيرفر يسجلها)
- ❌ **مفيش صوت بين الطرفين** — حد بيكلم حد لكن مفيش audio stream

السبب: السيرفر يتطلب TLS-SIP اللي يحتاج كود C/C++ (Linphone). React Native بدون native modules لا يقدر يفتح TLS socket. 

للحصول على مكالمة بصوت كامل، استخدم `FOXCALL.apk` الأصلي حتى يتم اتخاذ قرار معماري واحد من القرارات في قسم 5.
