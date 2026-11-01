"""مشخصات نسخه‌دار ماژول‌های تحلیل (Module Spec مطابق بخش ۷-۱)."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    version: str
    purpose: str
    inputs: str
    definition: str
    parameters: str
    outputs: str
    invalidation: str
    limitations: str
    tests: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        module_id="structure.bos",
        version="1.0.0",
        purpose="شناسایی شکست ساختار در جهت روند غالب",
        inputs="کندل‌های بسته H1/M5، swing_k=۳، ATR(14)",
        definition="بسته‌شدن قیمت بالاتر از آخرین Swing High تأییدشده (یا پایین‌تر از Swing Low) که قبلاً شکسته نشده است.",
        parameters="swing_k، حداقل فاصله بسته‌شدن بر حسب ATR، افق اعتبار",
        outputs="Evidence با جهت، شدت، سطح، ابطال و انقضا",
        invalidation="بسته‌شدن معکوس زیر/بالای سطح شکست",
        limitations="در بازار رِنج و کندل‌های پرنویز سیگنال کاذب تولید می‌کند؛ تعریف Swing به پارامتر حساس است.",
        tests="unit برای توالی swing/break؛ golden dataset؛ آزمون بدون look-ahead",
    ),
    ModuleSpec(
        module_id="structure.choch",
        version="1.0.0",
        purpose="تشخیص تغییر احتمالی کاراکتر بازار",
        inputs="سوئینگ‌های تأییدشده و وضعیت روند جاری",
        definition="شکست آخرین سوئینگ معتبر در خلاف جهت روند فعال؛ صرفاً هشدار تغییر، نه تضمین برگشت.",
        parameters="swing_k، buffer، افق اعتبار",
        outputs="Evidence با جهت مخالف روند قبلی",
        invalidation="بازگشت قیمت و ادامه روند قبلی",
        limitations="در رژیم‌های پرنوسان، CHoCH متعدد و متناقض رخ می‌دهد.",
        tests="unit روی داده ساختگی با الگوی مشخص؛ regression",
    ),
    ModuleSpec(
        module_id="structure.fvg",
        version="1.0.0",
        purpose="شناسایی شکاف ارزش منصفانه سه‌کندلی",
        inputs="سه کندل متوالی، ATR",
        definition="بالاخط: low[i] > high[i-2]؛ نزولی: high[i] < low[i-2]؛ حداقل عرض fvg_min_atr×ATR",
        parameters="fvg_min_atr، افق اعتبار، حداقل عرض",
        outputs="Evidence با ناحیه قیمتی",
        invalidation="بسته‌شدن خارج از ناحیه",
        limitations="پر شدن جزئی/کامل ناحیه در تعریف نسخه بعد باید دقیق شود.",
        tests="property test برای عرض مثبت و جهت؛ unit",
    ),
    ModuleSpec(
        module_id="structure.order_block",
        version="1.0.0",
        purpose="شناسایی آخرین کندل مخالف پیش از displacement",
        inputs="کندل‌ها، ATR، displacement_atr",
        definition="بدنه کندل > displacement_atr×ATR و بدنه/دامنه > ۰٫۶؛ آخرین کندل مخالف تا ۳ کندل قبل.",
        parameters="displacement_atr، حداکثر فاصله جستجو",
        outputs="Evidence با ناحیه و ابطال",
        invalidation="بسته‌شدن خارج از ناحیه Order Block",
        limitations="تعاریف منابع مختلف است؛ این نسخه عملیاتی و قابل آزمون است، نه تعریف واحد بازار.",
        tests="unit با displacement مصنوعی؛ golden",
    ),
    ModuleSpec(
        module_id="structure.liquidity_sweep",
        version="1.0.0",
        purpose="شناسایی جاروب نقدینگی و بازگشت",
        inputs="کندل جاری و بازه lookback",
        definition="عبور سایه از سقف/کف بازه و بازگشت بسته‌شدن به داخل؛ نسبت سایه ≥ ۰٫۳",
        parameters="sweep_lookback، حداقل نسبت سایه",
        outputs="Evidence با جهت معکوس جاروب",
        invalidation="بسته‌شدن فراتر از سطح جاروب",
        limitations="به کیفیت داده سایه و اسپرد حساس است.",
        tests="unit؛ آزمون داده با اسپرد بالا",
    ),
    ModuleSpec(
        module_id="structure.displacement",
        version="1.0.0",
        purpose="سنجش حرکت ایمپالس و قدرت بدنه",
        inputs="کندل، ATR",
        definition="بدنه > displacement_atr×ATR",
        parameters="displacement_atr",
        outputs="Evidence با جهت حرکت",
        invalidation="بازگشت کامل حرکت در افق کوتاه",
        limitations="در اخبار، displacement می‌تواند ناشی از spread/gap باشد.",
        tests="unit؛ بررسی جدا بودن از Order Block",
    ),
    ModuleSpec(
        module_id="trend.ema_structure",
        version="1.0.0",
        purpose="تعیین جهت و قدرت روند با ساختار میانگین‌ها و شیب",
        inputs="EMA(20/50/200)، ATR",
        definition="EMA20>EMA50>EMA200 و شیب مثبت → صعودی؛ قرینه → نزولی؛ در غیر این صورت خنثی",
        parameters="دوره‌ها، آستانه جدایی بر حسب ATR",
        outputs="Evidence جهت‌دار",
        invalidation="بسته‌شدن معکوس نسبت به EMA میانی",
        limitations="در رژیم رِنج سیگنال خنثی تولید می‌کند؛ همبستگی با مومنتوم باید کنترل شود.",
        tests="unit با سری خطی؛ golden",
    ),
    ModuleSpec(
        module_id="momentum.rsi_roc",
        version="1.0.0",
        purpose="سنجش مومنتوم با RSI و ROC",
        inputs="RSI(14)، ROC(10)، ATR",
        definition="RSI≥۵۵ و ROC>۰ → صعودی؛ RSI≤۴۵ و ROC<۰ → نزولی",
        parameters="rsi_period، roc_period، آستانه‌ها",
        outputs="Evidence جهت‌دار",
        invalidation="عبور RSI از میانه در جهت مخالف",
        limitations="در اشباع خرید/فروش می‌تواند دیر یا زود باشد؛ همبستگی با روند باید کنترل شود.",
        tests="unit؛ property برای بازه RSI",
    ),
    ModuleSpec(
        module_id="volatility.regime",
        version="1.0.0",
        purpose="طبقه‌بندی رژیم نوسان",
        inputs="ATR(14)، صدک ATR، نوسان تحقق‌یافته",
        definition="صدک ≥۸۰ نوسان بالا؛ ≤۲۰ نوسان پایین؛ در غیر این صورت متعادل",
        parameters="atr_period، پنجره صدک",
        outputs="Evidence خنثی (Context)",
        invalidation="تغییر رژیم در پنجره بعدی",
        limitations="معیار Context است و نباید به‌تنهایی سیگنال جهت‌دار بسازد.",
        tests="unit؛ بررسی خنثی بودن جهت",
    ),
    ModuleSpec(
        module_id="levels.key_level",
        version="1.0.0",
        purpose="شناسایی سطوح حمایت/مقاومت نزدیک قیمت",
        inputs="سقف/کف روز و هفته قبل، سطوح سشن، اعداد گرد، سوئینگ‌ها",
        definition="ادغام سطوح نزدیک (level_merge_pips) و صدور شاهد در فاصله level_proximity_pips",
        parameters="proximity_pips، merge_pips، حداقل فاصله تکرار",
        outputs="Evidence جهت‌دار با شدت محدود",
        invalidation="بسته‌شدن خارج از سطح",
        limitations="سطوح گذشته تضمین واکنش آینده نیستند؛ شدت عمداً پایین است.",
        tests="unit ادغام سطوح؛ golden",
    ),
    ModuleSpec(
        module_id="fundamental.event_surprise",
        version="1.0.0",
        purpose="به‌کارگیری غافلگیری داده اقتصادی منتشرشده",
        inputs="تقویم اقتصادی با actual/forecast و available_at",
        definition="انحراف actual از forecast نسبت به ارز پایه/مظنه؛ فقط رویدادهای در دسترس",
        parameters="lookback، حداقل غافلگیری، اهمیت",
        outputs="Evidence جهت‌دار",
        invalidation="اصلاح داده (revision)",
        limitations="کیفیت consensus و تأخیر انتشار منبع باید پایش شود.",
        tests="unit bitemporal؛ آزمون رویداد آینده نباید دیده شود",
    ),
    ModuleSpec(
        module_id="intermarket.correlation",
        version="1.0.0",
        purpose="استفاده از حرکت سری مرجع هم‌بسته",
        inputs="سری مرجع (مثلاً DXY) هم‌زمان با نماد",
        definition="همبستگی پنجره‌ای ≥ آستانه و z-score حرکت مرجع ≥ ۰٫۸",
        parameters="window، min_correlation، reference",
        outputs="Evidence جهت‌دار",
        invalidation="افت همبستگی زیر آستانه",
        limitations="همبستگی تاریخی تضمین رابطه آینده نیست؛ در تغییر رژیم باید خاموش شود.",
        tests="unit همبستگی؛ آزمون نبود هم‌زمانی",
    ),
)


def module_specs() -> list[dict[str, str]]:
    return [spec.to_dict() for spec in MODULE_SPECS]


def spec_by_id(module_id: str) -> ModuleSpec | None:
    for spec in MODULE_SPECS:
        if spec.module_id == module_id:
            return spec
    return None
