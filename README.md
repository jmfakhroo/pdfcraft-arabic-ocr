# pdfcraft-arabic-ocr

<div dir="rtl">

## التعرف الضوئي على النص العربي في PdfCraft

برنامج [PdfCraft](https://github.com/storytold/pdfcraft) لا يقرأ النص العربي في الملفات المصوّرة: محرّكه المدمج يقرأ الحروف اللاتينية فقط، وقائمة اللغات في نافذة التعرف الضوئي فيها الإنجليزية وحدها. هذه الأداة تضيف العربية إلى PdfCraft نفسه، وتضيف أمرًا يحوّل أي كتاب مصوّر إلى نسخة قابلة للبحث والنسخ.

جُرّبت على كتاب من 371 صفحة: خرج النص كاملًا تقريبًا، ويعمل البحث عن كلمات مثل "الله" و"الحمد" داخل PdfCraft.

### ماذا تضيف

- داخل PdfCraft: اختر Engine = Tesseract في نافذة Scan & OCR فيقرأ العربية بدل الإنجليزية.
- أمر `arabic-ocr` يكتب بجانب الملف نسخة قابلة للبحث (`book.ocr.pdf`) وملفًا نصيًا (`book.ocr.txt`)، والأصل لا يتغيّر.
- قائمة الزر الأيمن: Quick Actions في macOS، وOpen With في لينكس، وSend to في ويندوز.
- فحص ذاتي وإصلاح تلقائي (`arabic-ocr-doctor`) يعيد ضبط كل شيء بعد تحديث PdfCraft أو Tesseract.

### الجودة حسب النظام

| النظام | المحرّك | الحالة |
|---|---|---|
| macOS 14 أو أحدث | محرّك Apple للتعرف على النص (Live Text)، ويكمّل Tesseract السطور التي يفوتها | الأفضل، ومُختبَر على كتاب كامل |
| لينكس | RapidOCR (نموذج PP-OCRv5 العربي)، ويكمّل Tesseract السطور الضعيفة والناقصة | جيد، ومُختبَر داخل PdfCraft على لينكس |
| ويندوز 10 و11 | مثل لينكس | مُختبَر على ويندوز 11 مع PdfCraft 0.22: صفحة تجريبية واضحة قُرئت صحيحة، وكتاب قديم من 132 صفحة (طبعة 1315هـ) قُرئ جزء من كلماته فقط. لم يُختبر بعد داخل نافذة PdfCraft |

### التثبيت

macOS ولينكس:

```bash
curl -fsSL https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.sh | bash
```

ويندوز (في PowerShell):

```powershell
irm https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.ps1 | iex
```

المتطلبات: في macOS يلزم [Homebrew](https://brew.sh) وأدوات سطر الأوامر من Apple (يطلبها المثبّت إن لم تكن موجودة). في لينكس يثبّت المثبّت الحزم اللازمة بـ apt أو dnf أو pacman أو zypper وقد يطلب كلمة مرور sudo. في ويندوز يثبّت Python وTesseract عبر winget.

#### التثبيت بواسطة Claude Code

افتح Claude Code واكتب:

> ثبّت لي https://github.com/jmfakhroo/pdfcraft-arabic-ocr

ملف `CLAUDE.md` في المستودع يشرح لـ Claude خطوات التثبيت والتحقق لكل نظام.

### بعد التثبيت

1. أغلق PdfCraft وافتحه من جديد (في لينكس سجّل الخروج والدخول مرة واحدة).
2. داخل PdfCraft: Scan & OCR ثم In this file، واختر Engine = Tesseract، ثم Recognize text، ثم احفظ. اترك Document language على English، فهذا متوقَّع.
3. في macOS فقط: لتظهر الأداة في قائمة الزر الأيمن، انقر بالزر الأيمن على أي ملف PDF، ثم Quick Actions ثم Customize، وفعّل "Arabic OCR (PdfCraft)". هذه خطوة لمرة واحدة.

### الاستخدام من الطرفية

```bash
arabic-ocr book.pdf
arabic-ocr -o book.pdf          # ويفتح النتيجة في PdfCraft
arabic-ocr ~/Downloads/scans    # مجلد كامل، والنتائج في scans-ocr
arabic-ocr -f book.pdf          # يعيد قراءة كل الصفحات حتى التي فيها نص
arabic-ocr -k book.pdf          # يُبقي التشكيل في النص القابل للبحث
arabic-ocr-doctor               # فحص وإصلاح
```

بشكل افتراضي يُحذف التشكيل من النص المخفي القابل للبحث، لأن بحث PdfCraft لا يتجاهل الحركات: بدون الحذف لن تجد "الحمد" كلمة "الحمدُ". الصفحة نفسها تبقى كما هي بتشكيلها.

### حدود معروفة

- سطور الأحاديث بالخط العريض بين «» تأتي من Tesseract، ففيها أخطاء إملائية أحيانًا.
- الحواشي بالخط الصغير قد تُقرأ فيها بعض الأرقام خطأ.
- الخط الزخرفي (مثل البسملة المزخرفة) لا يُقرأ.
- في ويندوز ولينكس قد يسقط الرقم اللاتيني (مثل 2026) من بعض السطور العربية.
- الفارسية والأردية: استخدم `-e tesseract -l fas` أو `-l urd`، فمحرّك Apple لا يدعمهما.
- PdfCraft يخزّن الكلمات العربية بترتيب حروف معكوس، والأداة تعوّض ذلك. إن أصلح PdfCraft هذا في إصدار قادم فقد تنعكس الكلمات، وسيُشعرك الفحص الذاتي بالتحديث لتجرّب البحث عن كلمة.

### الإزالة

```bash
curl -fsSL https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/uninstall.sh | bash
```

في ويندوز: `irm https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/uninstall.ps1 | iex`

</div>

## Arabic OCR for PdfCraft (English)

[PdfCraft](https://github.com/storytold/pdfcraft) can't read Arabic in scanned PDFs: its built-in OCR engine only reads Latin script, and the OCR dialog only offers English. This adds Arabic to PdfCraft's own Scan & OCR, plus a command that turns any scanned book into a searchable copy.

Tested on a 371-page book: nearly all text came through, and PdfCraft's search finds words like "الله" and "الحمد".

### What you get

- In PdfCraft: set Engine = Tesseract in Scan & OCR and it reads Arabic instead of English.
- An `arabic-ocr` command that writes a searchable copy (`book.ocr.pdf`) and a text file (`book.ocr.txt`) next to the original, which stays untouched.
- A right-click entry: Quick Actions on macOS, Open With on Linux, Send to on Windows.
- `arabic-ocr-doctor`, a self-test that also repairs the setup after PdfCraft or Tesseract updates. On macOS and Linux it runs at login.

### Quality by system

| System | Engine | Status |
|---|---|---|
| macOS 14+ | Apple's text recognition (the Live Text engine), with Tesseract filling lines it misses | Best; tested on a full book |
| Linux | RapidOCR (PP-OCRv5 Arabic model), with Tesseract replacing weak or missing lines | Good; tested inside PdfCraft on Linux |
| Windows 10/11 | Same as Linux | Tested on Windows 11 with PdfCraft 0.22: a clean test page read correctly; an old 132-page print (1315 AH) was only partly correct. Not yet tested in the PdfCraft window |

### Install

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/install.ps1 | iex
```

macOS needs [Homebrew](https://brew.sh) and Apple's Command Line Tools (the installer asks for them if missing). On Linux the installer uses apt, dnf, pacman or zypper and may ask for your sudo password. On Windows it installs Python and Tesseract with winget.

To install with Claude Code, ask it: "Install https://github.com/jmfakhroo/pdfcraft-arabic-ocr for me". `CLAUDE.md` tells Claude how to install and verify it on each system.

### After installing

1. Quit and reopen PdfCraft (on Linux, log out and in once).
2. In PdfCraft: Scan & OCR, In this file, set Engine = Tesseract, Recognize text, then save. Leave Document language on English; that's expected.
3. macOS only, once: right-click any PDF, Quick Actions, Customize, and switch on "Arabic OCR (PdfCraft)".

### Command line

```bash
arabic-ocr book.pdf
arabic-ocr -o book.pdf          # and open the result in PdfCraft
arabic-ocr ~/Downloads/scans    # a whole folder; results go to scans-ocr
arabic-ocr -f book.pdf          # redo every page, even ones that already have text
arabic-ocr -k book.pdf          # keep harakat in the searchable text
arabic-ocr-doctor               # check and repair
```

Harakat are left out of the hidden searchable text by default, because PdfCraft's search doesn't ignore them ("الحمد" wouldn't find "الحمدُ"). The page image keeps them.

### How it works

PdfCraft finds Tesseract through the `PDFCRAFT_TESSERACT` setting and always calls it as `tesseract page.png stdout -l eng tsv`. The installer points that setting at `tesseract-for-pdfcraft`, which answers with an Arabic reading from the engine above, in Tesseract's TSV format. PdfCraft stores right-to-left words letter-reversed, so the helper hands each Arabic word over pre-reversed, which makes PdfCraft's search find it. The `arabic-ocr` command runs the same engine through [ocrmypdf](https://github.com/ocrmypdf/OCRmyPDF) as a plugin.

### Known limits

- Bold hadith lines in «» often come from Tesseract and can have spelling mistakes.
- Small-print footnotes can get some numbers wrong.
- Decorative calligraphy (an ornamental basmala, for example) isn't read.
- On Windows and Linux, Western numerals such as 2026 can drop out of Arabic lines.
- Persian and Urdu: use `-e tesseract -l fas` or `-l urd`; Apple's engine doesn't support them.
- If a future PdfCraft stops storing Arabic words reversed, words would come out backwards. The doctor notifies you when PdfCraft updates so you can search one word to check.

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/uninstall.sh | bash
```

Windows: `irm https://raw.githubusercontent.com/jmfakhroo/pdfcraft-arabic-ocr/main/uninstall.ps1 | iex`

### Credits and license

MIT license (see LICENSE). Not affiliated with PdfCraft. The installers download, and don't bundle: [Tesseract](https://github.com/tesseract-ocr/tesseract) and its [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) models (Apache 2.0), [ocrmypdf](https://github.com/ocrmypdf/OCRmyPDF) (MPL 2.0), and [RapidOCR](https://github.com/RapidAI/RapidOCR) with PaddleOCR's PP-OCRv5 models (Apache 2.0). Apple's text recognition is part of macOS.
