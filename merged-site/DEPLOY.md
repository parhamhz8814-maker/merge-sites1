# 🚀 راهنمای استقرار CP.Shop (Frontend + Backend)

این سند فقط برای این پروژه است: صفحه فروشگاه (RTL فارسی، `index.html`) + بک‌اند Python که هم API سفارش را می‌دهد و هم MCP را برای جستجوی کاتالوگ.

------------------------------------------------------------

## 1) ساختار پروژه

- Frontend (استاتیک):
  - `index.html`
  - `logos.html`
  - `robots.txt`
  - `sitemap.xml`
  - `run.md` / `README.md` (اختیاری)
  - `assets/`
  - `icons/` (اگر وجود دارد)

- Backend (Python): در پوشه `merged-backend/`
  - `cpshop_http.py`  (سرور HTTP: Static + API)
  - `cpshop_mcp.py`   (ابزارهای MCP برای جستجوی کاتالوگ)
  - `store_db.py`     (SQLite و منطق سفارش/پرداخت)
  - `catalog.json`
  - `security.py`
  - `shopping_cart.py`
  - فایل دیتابیس SQLite در زمان اجرا: `cpshop.db`

نکته مهم امنیتی/کارکردی:
- سایت Frontend فقط استاتیک است و نمی‌تواند رازها/توکن‌های بک‌اند را نگه دارد.
- endpointهای `/api/order` و `/api/order/pay` و `/mcp` باید روی سرور Python اجرا شوند.

------------------------------------------------------------

## 2) گزینه‌های Hosting برای Frontend (استاتیک)

در این پروژه، Frontend باید به یک Origin بک‌اند (Python) وصل شود. ساده‌ترین حالت این است که بک‌اند هم‌مبدأ (same origin) روی همان دامنه/پورت سرو کند. چون کد Frontend درخواست‌ها را با `fetch('/api/...')` و `fetch('/mcp')` انجام می‌دهد.

با این حال اگر اصرار به جداکردن Frontend و Backend دارید، باید Reverse Proxy یا تنظیمات same-origin انجام دهید (در بخش 5 توضیح داده شده).

### 2.1) GitHub Pages

1) یک ریپو برای فایل‌های استاتیک ایجاد کنید.
2) `index.html`، `logos.html`، `assets/`، `robots.txt`، `sitemap.xml` را اضافه کنید.
3) در Settings → Pages:
   - Branch را `main` (یا هر برنچی که فایلتان را قرار داده‌اید) انتخاب کنید.
   - Root را `/` بگذارید.
4) آدرس Pages را بگیرید (مثلاً `https://yourname.github.io/`).

پس از این کار، کدهای Frontend باید به بک‌اند API هم‌مبدأ متصل شوند.

### 2.2) Cloudflare Pages

1) وارد Cloudflare Pages شوید.
2) یک پروژه جدید بسازید.
3) فولدر استاتیک را (همان پوشه `merged-site/`) به عنوان root بدهید.
4) Framework preset معمولاً نیازی نیست؛ چون HTML خالص است.
5) در Settings:
   - Build command خالی بماند.
   - Output directory خالی یا `/`.
6) URL پروژه به شما داده می‌شود.

باز هم: برای کارکرد `fetch('/api/order')` باید same-origin یا reverse proxy پیاده شود.

### 2.3) Netlify

1) بروید به https://app.netlify.com/drop
2) کل فولدر `merged-site/` (یا فولدر شامل `index.html` و فایل‌های لازم) را در Drop قرار دهید.
3) از Site settings → Domain management، دامنه اختصاصی را اضافه کنید.

### 2.4) Vercel

1) یک Project جدید بسازید.
2) Root را روی فولدر استاتیک تنظیم کنید.
3) چون HTML است، Build step عملاً لازم نیست.
4) دامنه را در Project settings اضافه کنید.

------------------------------------------------------------

## 3) Custom Domain (دامنه اختصاصی)

### 3.1) پیش‌نیازها
- شما باید DNS دامنه را مدیریت کنید (Registrar یا DNS provider).

### 3.2) رکوردهای DNS (نمونه عمومی)

برای سرو استاتیک با Netlify / GitHub Pages / Cloudflare Pages معمولاً یکی از این روش‌ها است:

1) روش Nameserver:
   - Nameserverهای دامنه را به تنظیمات ارائه‌دهنده Pages تغییر دهید.

2) روش رکورد DNS (در صورت اینکه provider رکورد بدهد):
   - A record برای apex domain (`@`) به IP provider
   - CNAME برای `www` به آدرس provider

### 3.3) SSL
- برای اکثر providerها، SSL خودکار با Let’s Encrypt انجام می‌شود.
- بعد از ست شدن DNS، باید وضعیت HTTPS را سبز کنید.

------------------------------------------------------------

## 4) Backend Hosting (Python)

این بخش برای اجرای `cpshop_http.py` است.

### 4.1) کجا میزبانی شود؟
- VPS / Render / Railway / Fly.io / هر سرویس دیگر که Python را اجرا کند.

### 4.2) Command اجرا

از داخل پوشه `merged-backend/`:

- اجرای سرور:
  - `python cpshop_http.py 8765`

- بررسی liveness:
  - `GET http://localhost:8765/health`

### 4.3) محیط اجرا و env vars

در نسخه فعلی کد، env varهای ضروری به شکل صریح استفاده نشده‌اند.
اگر بعداً نسخه‌ای اضافه شد، در آن زمان سند به‌روزرسانی می‌شود.

### 4.4) SQLite persistence (مهم!)

- دیتابیس پروژه در فایل `merged-backend/cpshop.db` ساخته می‌شود.
- اگر هاست بک‌اند شما filesystem قابل‌پایداری (persistent storage) نداشته باشد:
  - با ریست سرویس، دیتابیس از بین می‌رود.
  - محصولات دوباره از `catalog.json` seed می‌شوند، اما سفارش‌های قبلی باقی نمی‌مانند.

راه‌حل:
- از سرویس/پلان با Volumes یا Persistent Disk استفاده کنید.
- یا قبل از ریست گرفتن، backup از `cpshop.db` تهیه کنید.

------------------------------------------------------------

## 5) راه‌حل same-origin برای API و MCP

Frontend درخواست می‌زند:
- `POST /api/order`
- `POST /api/order/pay`
- `POST /mcp`

پس بک‌اند باید روی همان Origin (scheme+host+port) قابل دسترس باشد.

### راه پیشنهادی: بک‌اند به عنوان Reverse Proxy/Single Origin

- یک Reverse Proxy مثل Nginx (یا تنظیمات مشابه در VPS) روی دامنه بگذارید.
- مسیرها:
  - `/` و فایل‌های HTML/استاتیک: از روی `merged-site/` سرو شود.
  - `/api/*` و `/mcp`: به `merged-backend` فوروارد شود.

### گزینه دیگر
- اگر بک‌اند بتواند خودش فایل‌های استاتیک را هم سرو کند، همین `cpshop_http.py` روی همان دامنه و پورت، کل سایت را سرو خواهد کرد.
- در این سناریو نیازی به hosting جدا برای Frontend نیست.

------------------------------------------------------------

## 6) File checklist (چیزهایی که باید آپلود کنید)

### 6.1) Frontend

- `merged-site/index.html`
- `merged-site/logos.html`
- `merged-site/assets/`
- `merged-site/robots.txt`
- `merged-site/sitemap.xml`
- `merged-site/icons/` (اگر وجود دارد)
- `merged-site/*.png` / `*.webp` / faviconها (در صورت وجود)

### 6.2) Backend

- کل پوشه `merged-backend/`
- فایل‌های ضروری:
  - `cpshop_http.py`, `cpshop_mcp.py`, `store_db.py`, `security.py`, `shopping_cart.py`
  - `catalog.json`

فایل SQLite `cpshop.db`:
- اگر میزبان شما persistent disk دارد: آپلود کنید یا در اولین اجرا اجازه دهید ساخته شود.
- اگر persistent disk ندارید: انتظار داشته باشید با ریست پاک شود.

------------------------------------------------------------

## 7) Post-deploy checks (بعد از استقرار حتما چک کنید)

1) HTTPS فعال است؟ (در مرورگر بدون خطا باز شود)
2) `index.html` لود می‌شود و فونت Vazirmatn بدون خطا دانلود می‌شود.
3) صفحه RTL درست است: متن فارسی به شکل راست‌چین نمایش داده شود.
4) API بک‌اند پاسخ می‌دهد:
   - `GET /health`
5) تست سفارش:
   - از طریق UI یک سفارش نمایشی ثبت کنید.
   - endpointهای `/api/order` و `/api/order/pay` از نظر وضعیت JSON درست کار کنند.
6) `robots.txt` و `sitemap.xml` قابل دسترس هستند.

------------------------------------------------------------

## 8) نکات RTL و UTF-8

- همه صفحات باید با UTF-8 سرو شوند (در HTML با `meta charset="UTF-8"` رعایت شده است).
- در هاست/Reverse Proxy مطمئن شوید محتوای HTML با charset درست ارسال می‌شود.
- `dir="rtl"` و `lang="fa"` در `index.html` لحاظ شده است.

------------------------------------------------------------

اگر خواستید، مرحله reverse-proxy را دقیقاً متناسب با هاست/دامنه شما (Nginx یا تنظیمات provider) هم می‌نویسم.
