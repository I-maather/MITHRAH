"""
The daily pipeline — خط القرار.

الترتيب إلزامي، وكل مرحلة تستطيع إيقاف الخط بقرار NO_TRADE:

  0. Kill Switch gate
  1. Market Regime / Market status
  2. Macro Risk  (veto only)
  3. Scheduled News Risk (veto only)
  4. Technical State + Market Structure  (داخل الاستراتيجية)
  5. Strategy Eligibility
  6. Risk Review
  7. Order Preview
  8. Execution
  9. Reconciliation
 10. Audit

Macro و News يستطيعان المنع فقط، ولا يستطيعان فرض صفقة.
كل نتيجة — بما فيها NO_TRADE — تُكتب في Audit Log.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, Sequence

from ..audit.log import Actor, AuditAction, AuditLog
from ..brokers.base import BrokerAdapter, BrokerNotConnected
from ..clock import now_utc, forex_market_status
from ..contracts import Bar, Decision, RiskDecision, Signal
from ..eligibility.allowlist import CFD_ASSET_CLASSES, check_eligibility
from ..execution.orders import (
    ExecutionService,
    SubmissionOutcome,
    SubmissionResult,
    build_order_intent,
    reconcile,
)
from ..killswitch.engine import KillSwitch, KillSwitchTrigger
from ..money import D
from ..risk.constitution import NEWS_BLACKOUT_MINUTES
from ..risk.capital_costs import CfdTradeEconomics
from ..risk.costs import CommissionSchedule, CostAssumptions
from ..risk.engine import RiskEngine, SessionRiskState
from ..risk.instrument_registry import InstrumentRegistry
from ..strategies.base import Strategy


@dataclass(frozen=True)
class MacroAssessment:
    """يمنع فقط. لا يستطيع فرض صفقة."""

    blocks_trading: bool
    reason_ar: str


@dataclass(frozen=True)
class NewsBlackout:
    symbol: Optional[str]
    starts_utc: datetime
    ends_utc: datetime
    title_ar: str
    source: str

    def covers(self, at: datetime, symbol: str) -> bool:
        if self.symbol is not None and self.symbol != symbol:
            return False
        return self.starts_utc <= at <= self.ends_utc


@dataclass
class BlackoutCalendar:
    """
    تقويم حظر يدوي. لا نخترع أخباراً: إن لم يوجد مصدر رسمي موثوق،
    نستخدم هذا التقويم اليدوي، وإن كان فارغاً وغير مؤكد => NO_TRADE.
    """

    entries: list[NewsBlackout] = field(default_factory=list)
    confirmed_for: set[date] = field(default_factory=set)

    def is_confirmed(self, day: date) -> bool:
        return day in self.confirmed_for

    def active(self, at: datetime, symbol: str) -> Optional[NewsBlackout]:
        for e in self.entries:
            if e.covers(at, symbol):
                return e
        return None


def _at_pip(value: Decimal, pip: Decimal) -> str:
    """
    رقمُ سعرٍ بدقّة نقطة أداته — منزلةٌ عُشرية إضافية لا أكثر.

    القسمة في `Decimal` تُخرج ثمانياً وعشرين منزلة، وتسرّبها إلى نصٍّ
    تقرأه المالكة يجعل الرقم غير مقروء — فيُقرأ عطباً وهو صحيح.
    """
    if pip is None or pip <= 0:
        return format(value, "f")
    places = max(0, -pip.normalize().as_tuple().exponent) + 1
    # **وقيمةٌ أصغر من نقطةٍ تُرى.** أدنى وقفٍ على الذهب `0.001` وحجم نقطته
    # `0.01`: القصُّ على منازل النقطة وحدها يطبعه «0.000» — أي يمحو الرقم
    # الذي جاء السطر ليقوله. فتُوسَّع المنازل بقدر ما يُظهر ثلاثة أرقامٍ
    # دالّة، وتُقصَر عند عشرٍ كي لا يعود الطول.
    if value != 0:
        places = max(places, -value.normalize().adjusted() + 2)
    places = min(places, 10)
    return format(value.quantize(Decimal(1).scaleb(-places)), "f")


def is_cfd(details) -> bool:
    """
    أهذه الأداة عقد فروقات؟

    **بالمُسنَد نفسه الذي وجّه فحص الأهلية** (`allowlist.py:139`)، لا بنسخةٍ
    منه: نسخةٌ ثانية من الشرط تعني أن أداةً تُفحَص أهليتها كـCFD ثم تُسعَّر
    كسهم — وهو بالضبط ما وقع.
    """
    return getattr(details, "asset_class", None) in CFD_ASSET_CLASSES


#: رمزُ رفضٍ جديد: أداة CFD بلا اقتصادياتٍ مقيسة.
INSTRUMENT_ECONOMICS_UNMEASURED = "INSTRUMENT_ECONOMICS_UNMEASURED"
#: وقفُ الإشارة أضيق مما يقبله الوسيط.
#:
#: الاسم المُعتمَد صار `BROKER_MIN_STOP_DISTANCE_VIOLATION` كي يُقرأ في
#: قمع الفرص بمعزلٍ عن «مواصفةٍ غير محلولة» — الأوّل يُصلَح بقرارٍ على
#: الإطار أو الوقف، والثاني بإعادة قياس. والاسم القديم يبقى مرادفاً.
STOP_BELOW_BROKER_MINIMUM = "BROKER_MIN_STOP_DISTANCE_VIOLATION"
#: مواصفةٌ أُعلنت بلا وحدةٍ تحلّها.
INSTRUMENT_SPEC_UNRESOLVED = "INSTRUMENT_SPEC_UNRESOLVED"
#: استراتيجيةٌ تُشغَّل على إطارٍ لم يُعتمَد لها — فلا تُقيَّم.
TIMEFRAME_MISMATCH = "TIMEFRAME_MISMATCH"
#: نفسه، لكن بموافقةٍ مُسمّاة على التجريبي — تُقيَّم ويُوسَم أنها دليلٌ أماميّ.
TIMEFRAME_EXCEPTION = "TIMEFRAME_EXCEPTION_DEMO_TRIAL"
#: كل الاستراتيجيات المعتمدة سقطت على بوابة الإطار — سببٌ يخصّ الإعداد لا السوق.
NO_STRATEGY_FOR_TIMEFRAME = "NO_STRATEGY_APPROVED_FOR_TIMEFRAME"
#: أُقدِم على هذا الإعداد بعينه في هذه الدورة الزمنية من قبل.
ENTRY_ALREADY_ATTEMPTED = "ENTRY_ALREADY_ATTEMPTED_FOR_SETUP"
#: تعذّرت قراءة مراكز الوسيط — ولا يُفتَح مركزٌ على جهلٍ بما هو مفتوح.
PORTFOLIO_READ_FAILED = "PORTFOLIO_READ_FAILED"


#: مفرداتان لشيءٍ واحد: الوسيط يسمّي الدقّة `HOUR_4` والاستراتيجيات
#: تُعلن `4H`. ومقارنةُ الاسمين نصّاً تُسقط تطابقاً حقيقياً — وهو صنف
#: العطل نفسه بوجهٍ لغوي: طرفان لمعنىً واحد، كلٌّ بلغته.
#:
#: فتُوحَّد الكلمة **في موضعٍ واحد** قبل أي مقارنة.
def _canonical_timeframe(value) -> str:
    if not value:
        return ""
    text = str(value).strip().upper()
    return TIMEFRAME_NAMES.get(text, text)


def _allowed_timeframes(meta) -> tuple[str, ...]:
    """الأطر المسموح بها لهذه الاستراتيجية — بصيغةٍ تحتمل بياناتٍ قديمة."""
    getter = getattr(meta, "allowed_timeframes", None)
    if getter:
        return tuple(_canonical_timeframe(tf) for tf in getter if tf)
    declared = getattr(meta, "timeframe", None)
    return (_canonical_timeframe(declared),) if declared else ()


def _runs_on(meta, running_on) -> bool:
    running = _canonical_timeframe(running_on)
    if not running:
        return True
    allowed = {_canonical_timeframe(tf) for tf in _allowed_timeframes(meta)}
    return running in allowed


#: أسماء الأطر كما يسمّيها الوسيط ⇐ كما تُعلنها الاستراتيجيات.
#:
#: كل استراتيجيةٍ تُعلن `metadata.timeframe`، ولا يقرأه شيء. جرّبتُ البحث
#: في الخادم كلّه: يظهر عند تعريفه وفي أربعة نصوصٍ حرفية، ولا مقارنة.
#:
#: وأثرُه ليس نظرياً: `DEMO_TRIAL_RESOLUTION` يقبل خمسة أطر، فتُشغَّل
#: استراتيجيةٌ تُعلن «1D» على شمعة ربع ساعة. وعلى EURUSD تُرفض عند حدّ
#: الوسيط فيُكشف الخلط؛ وعلى الذهب — حدُّه عُشر سنت — **تمرّ وتُنفَّذ**.
#: أي أن الخلط نفسه يُكشف على أداةٍ ويصمت على أخرى.
#:
#: ولا يُمنع التشغيل على إطارٍ آخر: التجريبي موضعُ اختبار الفرضيات. لكنه
#: **يُقال**، فتُقرأ النتيجة على أنها فرضيةٌ أخرى لا الفرضية المعلَنة.
TIMEFRAME_NAMES = {
    "DAY": "1D", "HOUR_4": "4H", "HOUR": "1H",
    "MINUTE_30": "30M", "MINUTE_15": "15M",
}

@dataclass(frozen=True)
class CfdReview:
    """نتيجة بناء اقتصاديات CFD: إمّا أرقام، وإمّا سببٌ يُقرأ."""

    economics: Optional[CfdTradeEconomics] = None
    reason_code: Optional[str] = None
    reason_ar: str = ""


@dataclass(frozen=True)
class PipelineResult:
    decision: Decision
    reason_code: Optional[str]
    reason_ar: str
    stage: str
    signal: Optional[Signal] = None
    risk_decision: Optional[RiskDecision] = None
    submission: Optional[SubmissionResult] = None
    reconciliation_ok: Optional[bool] = None
    at_utc: datetime = field(default_factory=now_utc)
    #: تشخيص كل استراتيجية شُغّلت — «لماذا لم تُشِر» بالأرقام.
    #: فارغةٌ حين يقف الخط قبل مرحلة الاستراتيجية، وذلك صادق: لم تُسأل.
    assessments: tuple = ()

    @property
    def one_line_ar(self) -> str:
        if self.decision is Decision.TRADE:
            return f"تنفيذ: {self.reason_ar}"
        if self.decision is Decision.HALTED:
            return f"متوقف: {self.reason_ar}"
        return f"لا تداول اليوم — {self.reason_ar}"


def strategy_key(strategy) -> str:
    """`الاسم@الإصدار` بحروفٍ كبيرة — الهوية الوحيدة التي تُطابَق بها."""
    meta = strategy.metadata
    return f"{meta.name}@{meta.version}".upper()


class Pipeline:
    def __init__(
        self,
        *,
        broker: BrokerAdapter,
        risk_engine: RiskEngine,
        kill_switch: KillSwitch,
        audit: AuditLog,
        execution: ExecutionService,
        strategies: Sequence[Strategy],
        schedule: CommissionSchedule,
        assumptions: CostAssumptions,
        blackouts: BlackoutCalendar,
        allow_live_submission: bool = False,
        #: أسماء استراتيجيات مسموحة **على التجريبي وحده**. انظري
        #: `app/runtime/demo_trial.py`. فارغةٌ في كل مسارٍ آخر.
        trial_strategies: frozenset[str] = frozenset(),
        #: اقتصاديات الأدوات المقيسة من الوسيط. فارغةٌ ⇒ لا قرار CFD.
        instruments: Optional[InstrumentRegistry] = None,
        #: الإطار المُشغَّل — يُقارَن بما تُعلنه كل استراتيجية.
        resolution: str = "DAY",
        #: **استثناءٌ مُسمّى** يسمح بتشغيل استراتيجيةٍ على إطارٍ لم يُعتمَد
        #: لها — على التجريبي وحده وبمرجع موافقةٍ من المالكة.
        #:
        #: بلا هذا يقع أحد أمرين، وكلاهما خطأ: إمّا تُشغَّل الاستراتيجيات
        #: على أي إطار بصمت (وهو ما كان: ٧١٥٤ حدث تعارضٍ مكتوبٍ لا يمنع)،
        #: وإمّا يتوقّف جمع الأدلة الأمامية كلّه لأن لا إطار معتمَد بعد.
        #:
        #: والاستثناء **يُقال في كل دورة**، ويحمل مرجعه، ويُوسم به القرار.
        timeframe_exception_reference: str = "",
    ) -> None:
        self.broker = broker
        self.risk = risk_engine
        self.kill_switch = kill_switch
        self.audit = audit
        self.execution = execution
        self.strategies = list(strategies)
        self.schedule = schedule
        self.assumptions = assumptions
        self.blackouts = blackouts
        self.allow_live_submission = allow_live_submission
        self.trial_strategies = frozenset(trial_strategies)
        self.instruments = instruments if instruments is not None else InstrumentRegistry.empty()
        self.resolution = resolution
        self.timeframe_exception_reference = timeframe_exception_reference
        # ---------------------------------------------------------------
        # **إعدادٌ واحد ⇒ محاولةُ دخولٍ واحدة.**
        #
        # الحلقة تدور كل ٦٠ ثانية، والشمعة أربع ساعات. فإشارةٌ صحيحة على
        # شمعةٍ واحدة تتكرّر **٢٤٠ مرّة**، وكلُّ تكرارٍ نيّةُ أمرٍ جديدة.
        #
        # ووقع ذلك في 2026-09-03: أربع دورات متتالية على الشمعة نفسها،
        # أنتجت أربع نيّات بأربعة مفاتيح مختلفة — لأن المفتاح يحمل سعر
        # الدخول، وهو يتغيّر مع كل عرضٍ من الوسيط. فحارسُ التكرار لم يرَ
        # تكراراً حتى ثبت السعر بين دورتين، فانطلق قاطع الطوارئ ونُسب
        # السبب إلى «أمر مكرر» — وهو أثرٌ لا سبب.
        #
        # والبوابات الموجودة تقرأ من قاعدة البيانات (مركزٌ مفتوح، أوامرُ
        # اليوم)، وهي لا تعرف شيئاً قبل أن يُملأ أمرٌ ويُسجَّل. فبين
        # الإرسال والتسجيل نافذةٌ تتّسع لكل دوراتِ الشمعة.
        #
        # ⇒ حارسٌ في الذاكرة على **الإعداد** لا على النيّة: (اليوم، الأداة،
        # الاستراتيجية، بداية الشمعة). شمعةٌ جديدة إعدادٌ جديد، والشمعة
        # نفسها محاولةٌ واحدة. والبوابات الدستورية تبقى فوقه كما هي.
        # ---------------------------------------------------------------
        self._attempted_setups: set[tuple] = set()

    # -- helpers ------------------------------------------------------------
    def _no_trade(self, stage: str, code: str, message: str, at: datetime) -> PipelineResult:
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.NO_TRADE, decision=code,
            reason_ar=message, source=stage, at=at,
        )
        return PipelineResult(Decision.NO_TRADE, code, message, stage, at_utc=at)

    def cfd_review(self, signal: Signal) -> CfdReview:
        """
        اقتصاديات هذه الإشارة **من قياس الوسيط**، لا من جدول عمولاتٍ لوسيطٍ آخر.

        ## لماذا هذه دالّة لا سطرٌ داخل `run`

        لأن الخطأ الذي تصلحه كان سطراً داخل `run`: كان الخط يستدعي
        `risk.evaluate` — مسار **أسهم IBKR** — على كل صفقة، بعمولات
        `IBKR_PRO_TIERED_US_STOCK` وبكميةٍ تُحلّ عكسياً بالسهم الواحد. بينما
        `evaluate_cfd` و`CapitalComCostModel` و`InstrumentRegistry` — أي كل
        ما قيس من الوسيط فعلاً — لم يكن يُستدعى إلا في الظلّ
        (`shadow.py`). فالنظام كان **يقيس اقتصاديات كابيتال، ويعرضها،
        ويقرّر بغيرها**.

        وسطرٌ داخل `run` لا يُستدعى من اختبارٍ إلا بتشغيل الخط كاملاً؛
        فيُكتب له اختبارٌ ينسخ منطقه، ونسخةٌ في اختبار لا تسقط حين يتغيّر
        الأصل. فالمنطق هنا، والاختبار يستدعيه.

        ## والكمية ليست متغيّراً

        كابيتال يفرض كميةً دنيا (100 وحدة على EUR/USD، و0.01 أونصة على
        الذهب). فالسؤال ليس «كم أشتري؟» بل «هل الخسارة الكاملة عند الكمية
        الدنيا تقع ضمن الميزانية؟». والجواب لا ⇒ لا صفقة، ولا تصغير.
        """
        model = self.instruments.cost_model_for(signal.symbol)
        if model is None:
            return CfdReview(
                reason_code=INSTRUMENT_ECONOMICS_UNMEASURED,
                reason_ar=self.instruments.why_not(signal.symbol),
            )

        pip = model.economics.pip_size
        if pip <= 0:
            return CfdReview(
                reason_code=INSTRUMENT_ECONOMICS_UNMEASURED,
                reason_ar=f"{signal.symbol}: حجم النقطة غير صالح في القياس.",
            )

        stop_price_distance = abs(signal.entry_price - signal.stop_price)
        tp_price_distance = abs(signal.take_profit_price - signal.entry_price)
        if stop_price_distance <= 0:
            return CfdReview(
                reason_code=STOP_BELOW_BROKER_MINIMUM,
                reason_ar="لا صفقة بلا وقف: مسافة الوقف صفر.",
            )

        # أدنى مسافة وقف يفرضها الوسيط. تجاوزُها يعني أمراً يُرفَض عنده —
        # ورفضُه هناك أغلى من رفضنا هنا، لأنه يقع بعد أن صار للأمر أثر.
        # **الحدّ يُحلّ إلى وحدة السعر قبل المقارنة.**
        #
        # كان يُقارَن خاماً، وهو عند Capital.com نسبةٌ مئوية
        # (`{"unit":"PERCENTAGE","value":0.01}`) ⇒ ٠٫٠١ سعراً = ١٠٠ نقطة على
        # اليورو والحدُّ الحقيقي ١٫١٦ نقطة. وبين ٣٠ أغسطس و٣ سبتمبر ٢٠٢٦
        # رُفضت ٤٨٦ إشارة من ٤٨٦ هنا — ولم تبلغ ولا واحدةٌ بوابةَ المخاطر.
        if model.economics.stop_spec_unresolved:
            return CfdReview(
                reason_code=INSTRUMENT_SPEC_UNRESOLVED,
                reason_ar=(
                    f"{signal.symbol}: أدنى مسافة وقف مُعلَنة "
                    f"{model.economics.min_stop_distance} بوحدةٍ مجهولة — "
                    "قياسٌ قديم قبل حفظ الوحدة. أعيدي "
                    "scripts/discover_instrument_economics.py."
                ),
            )
        minimum = model.economics.min_stop_price_at(signal.entry_price)
        if minimum is not None and stop_price_distance < minimum:
            return CfdReview(
                reason_code=STOP_BELOW_BROKER_MINIMUM,
                reason_ar=(
                    # **الرقم بدقّة الأداة، لا بدقّة القسمة.**
                    #
                    # ظهر على شاشة المالكة: «مسافة الوقف
                    # 0.0023321165761706818242605020» — ثمانٍ وعشرون منزلة،
                    # وهي دقّة `Decimal` بعد قسمةٍ لا دقّةُ سعرٍ عند وسيط.
                    # ورقمٌ بهذا الطول لا يُقرأ، فيُقرأ أنه عطب.
                    #
                    # والدقّة تُشتقّ من حجم نقطة الأداة نفسها — 0.0001 على
                    # اليورو و0.01 على الذهب — فتصحّ للأربع بلا جدول.
                    f"مسافة الوقف {_at_pip(stop_price_distance, pip)} أضيق من أدنى "
                    f"ما يقبله الوسيط ({_at_pip(minimum, pip)}) على {signal.symbol}"
                    f" — أي {_at_pip(stop_price_distance / pip, D('0.1'))} نقطة "
                    f"مقابل {_at_pip(minimum / pip, D('0.1'))}. "
                    "ولا يُوسَّع الوقف تلقائياً: التوسيع يغيّر المخاطرة التي وافقتِ عليها."
                ),
            )

        try:
            economics = model.estimate(
                size=model.economics.min_deal_size,
                entry_price=signal.entry_price,
                stop_distance_pips=stop_price_distance / pip,
                take_profit_distance_pips=tp_price_distance / pip,
            )
        except (ValueError, ArithmeticError) as exc:
            return CfdReview(
                reason_code=INSTRUMENT_ECONOMICS_UNMEASURED,
                reason_ar=f"تعذّر حساب اقتصاديات {signal.symbol}: {exc}",
            )
        return CfdReview(economics=economics)

    def runnable_strategies(self) -> list:
        """
        الاستراتيجيات التي يحقّ لها أن تُقيّم الآن.

        **دالّة لا سطرٌ داخل `run`** عن قصد: كانت منطقاً مكتوباً في موضع
        واحدٍ يستحيل استدعاؤه من اختبارٍ بلا تشغيل الخط كاملاً، فكُتب له
        اختبارٌ **ينسخ المنطق** — ونسخةٌ في اختبار لا تسقط حين يتغيّر الأصل.
        وهو العطل الحاكم في هذا المشروع مرّةً أخرى: اختبارٌ يمرّ لسببٍ غير
        الذي كُتب له.

        فالمنطق هنا، ويُستدعى من الاختبار كما يُستدعى من `run`.
        """
        approved = [s for s in self.strategies if s.metadata.state.value == "APPROVED"]
        # **المطابقة بالمفتاح الكامل `الاسم@الإصدار` لا بالاسم.**
        #
        # `TrendPullbackV1` و`TrendPullbackV2` يحملان الاسم نفسه
        # (`TREND_PULLBACK`) ويختلفان بالإصدار. فمطابقةُ الاسم وحده تُشغّل
        # الاثنين معاً — ومنهما واحدةٌ كُتبت لأسهمٍ أمريكية.
        #
        # وقد وقع الأسوأ من ذلك فعلاً: كُتب في الإعداد `TREND_PULLBACK_V2`
        # وهو **لا يطابق أي استراتيجية**، فلم تُشغَّل الاستراتيجية الرئيسية
        # إطلاقاً — **بصمت**. اسمٌ في إعدادٍ لا يوافق هويّةً في السجلّ، ولا
        # أحد يقول شيئاً. وهو العطل الحاكم في هذا المشروع مرّةً أخرى.
        # الاستثناء التجريبي — مقفلٌ على الوسيط **هنا**، عند موضع الاستعمال،
        # لا عند موضع البناء وحده. و`getattr(..., True)` تُغلق عند غياب
        # الصفة: وسيطٌ لا نعرف نوعه يُعامَل معاملة الحقيقي.
        if self.trial_strategies and getattr(self.broker, "is_live", True) is False:
            already = {id(s) for s in approved}
            approved += [
                s for s in self.strategies
                if id(s) not in already
                and strategy_key(s) in self.trial_strategies
                and s.metadata.state.value != "DISABLED"
            ]
        return approved

    # -- main ---------------------------------------------------------------
    def run(
        self,
        *,
        symbol: str,
        bars: Sequence[Bar],
        state: SessionRiskState,
        macro: MacroAssessment,
        now: Optional[datetime] = None,
    ) -> PipelineResult:
        now = now or now_utc()
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.PIPELINE_RUN, decision="START",
            reason_ar=f"بدء خط القرار للرمز {symbol}.", source="Pipeline", at=now,
        )

        # 0) Kill Switch
        if not self.kill_switch.allows_new_entries():
            ev = self.kill_switch.state.current_event
            message = f"Kill Switch مفعّل: {ev.reason_ar if ev else 'سبب غير مسجل'}"
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.NO_TRADE, decision="HALTED",
                reason_ar=message, source="KillSwitch", at=now,
            )
            return PipelineResult(Decision.HALTED, "KILL_SWITCH_ACTIVE", message, "kill_switch", at_utc=now)

        # 1) Broker + market status
        try:
            if not self.broker.health_check():
                raise BrokerNotConnected("فحص صحة الوسيط فشل")
            balances = self.broker.get_balances(self.broker.get_accounts()[0])
            permissions = self.broker.get_trading_permissions(balances.account_id)
            quote = self.broker.get_market_data(symbol)
            details = self.broker.get_instrument_details(symbol)
        except BrokerNotConnected as exc:
            self.kill_switch.trigger(
                KillSwitchTrigger.BROKER_DISCONNECTED, reason_ar=str(exc), at=now
            )
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision="BROKER_DISCONNECTED", reason_ar=str(exc), source="Pipeline", at=now,
            )
            return PipelineResult(Decision.HALTED, "BROKER_DISCONNECTED", str(exc), "broker", at_utc=now)
        except Exception as exc:  # noqa: BLE001
            return self._no_trade("broker", "BROKER_ERROR", f"خطأ من الوسيط: {exc}", now)

        market = forex_market_status(now)

        # 2) Macro veto
        if macro.blocks_trading:
            return self._no_trade("macro", "MACRO_VETO", macro.reason_ar, now)

        # 3) News blackout
        if not self.blackouts.is_confirmed(now.date()):
            return self._no_trade(
                "news",
                "NEWS_CALENDAR_UNCONFIRMED",
                "تقويم الأخبار لهذا اليوم غير مؤكد. النظام لا يخترع أخباراً — القرار NO_TRADE.",
                now,
            )
        active_blackout = self.blackouts.active(now, symbol)
        if active_blackout is not None:
            return self._no_trade(
                "news", "NEWS_BLACKOUT",
                f"نافذة حظر أخبار نشطة: {active_blackout.title_ar} (المصدر: {active_blackout.source}).",
                now,
            )

        # ---------------------------------------------------------------
        # ٣٫٥) ما هو مفتوحٌ **قبل** هذه الدورة — يُقرأ من الوسيط.
        #
        # النظام لا يحتفظ بدفتر مراكز مفتوحة، و`local_positions` في
        # المطابقة أدناه لم تكن إلا المركز الذي فُتح في هذه الدورة. فكانت
        # تُقارَن بحساب الوسيط **كلّه**، فيظهر أيُّ مركزٍ ثانٍ على أداةٍ
        # أخرى «غير معروفٍ لدينا» ويرتفع قاطع الطوارئ. ومعناه أن سقف
        # «ثلاثة مراكز» في الدستور غير قابلٍ للبلوغ: الثاني يوقف النظام
        # في الدورة التي تليه. وقع اليوم على GOLD بعد GBPUSD بدقيقة.
        #
        # وقراءةُ ما هو مفتوحٌ قبل التنفيذ تُعطي المطابقةَ خطَّ أساسها بلا
        # ادّعاء دفترٍ لا نملكه: يُطابَق الحسابُ كلُّه، والسؤال يصير
        # «هل تغيّر شيءٌ غير الذي فعلناه؟» — وهو السؤال الصحيح.
        #
        # ودفترُ المراكز المفتوحة يبقى **عيباً مفتوحاً مسجَّلاً**: بلا
        # سجلٍّ يعبر إعادةَ التشغيل لا تُبنى مطابقةٌ تصمد عبرها.
        # ---------------------------------------------------------------
        try:
            positions_before = list(self.broker.get_positions(balances.account_id))
        except Exception as exc:  # noqa: BLE001
            return self._no_trade(
                "portfolio", PORTFOLIO_READ_FAILED,
                f"تعذّرت قراءة المراكز المفتوحة من الوسيط: {type(exc).__name__}. "
                "ولا تُبنى مطابقةٌ على جهلٍ بما هو مفتوح.",
                now,
            )

        # 4/5) Eligibility
        eligibility = check_eligibility(
            symbol=symbol, quote=quote, details=details, permissions=permissions,
            balances=balances, market_is_open=market.is_open,
            minutes_since_open=market.minutes_since_open,
            minutes_to_close=market.minutes_to_close, now=now,
        )
        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.ELIGIBILITY_DECISION,
            decision="ELIGIBLE" if eligibility.eligible else (eligibility.reason_code or "INELIGIBLE"),
            reason_ar=eligibility.reason_ar, source="Eligibility",
            after={"checks": [list(c) for c in eligibility.checks]}, at=now,
        )
        if not eligibility.eligible:
            return PipelineResult(
                Decision.NO_TRADE, eligibility.reason_code, eligibility.reason_ar, "eligibility", at_utc=now
            )

        # 5b) Strategy — APPROVED فقط، وتجربةُ التجريبي استثناءٌ مُسمّى
        #
        # الاستثناء **مقفلٌ على الوسيط هنا أيضاً**، لا في مكان البناء وحده:
        # حارسٌ في موضع البناء يمرّ من حوله أي مسارٍ يبني الخط بنفسه — وهذا
        # موضع الاستعمال. و`getattr(..., True)` تُغلق عند غياب الصفة: وسيطٌ
        # لا نعرف نوعه يُعامَل معاملة الحقيقي.
        approved = self.runnable_strategies()
        if not approved:
            return self._no_trade(
                "strategy", "NO_APPROVED_STRATEGY",
                "لا توجد استراتيجية معتمدة. كل الاستراتيجيات في حالة بحث أو معطّلة.", now,
            )

        # **الإطار المُعلَن يُقارَن بالإطار المُشغَّل، ويُقال الخلاف.**
        running_on = TIMEFRAME_NAMES.get(
            str(getattr(self, "resolution", "") or "").upper(), None
        )
        signal: Optional[Signal] = None
        assessments: list[tuple[str, object]] = []
        skipped_for_timeframe: list[str] = []
        for strategy in approved:
            meta = strategy.metadata
            # ---------------------------------------------------------------
            # **الإطار بوابةٌ الآن، لا ملاحظة.**
            #
            # كان يُسجَّل `TIMEFRAME_MISMATCH` ويُشغَّل الأمر على أي حال —
            # ٧١٥٤ حدثاً في يومٍ واحد، كلّها مكتوبة ولا يمنع منها شيء.
            # ونتيجةُ استراتيجيةٍ تُعلن «1D» وتُقاس على «4H» ليست نتيجة
            # فرضيتها: هي فرضيةٌ أخرى تحمل اسمها.
            #
            # ولا يُمنع التشغيل على إطارٍ آخر مطلقاً — يُعتمَد بدليلٍ مُسمّى
            # في `approved_timeframes`، ثم يُشغَّل.
            # ---------------------------------------------------------------
            if not _runs_on(meta, running_on):
                allowed = "، ".join(_allowed_timeframes(meta))
                exception_ref = self.timeframe_exception_reference
                if exception_ref and not self.broker.is_live:
                    # استثناءٌ **مُسمّى وموسوم**: يُشغَّل على التجريبي بمرجع
                    # موافقةٍ، ونتيجتُه دليلٌ أمامي لهذا الإطار — لا دليلٌ
                    # على الفرضية المعلَنة.
                    self.audit.record(
                        actor=Actor.PIPELINE, action=AuditAction.CONFIG_CHANGE,
                        decision=TIMEFRAME_EXCEPTION,
                        reason_ar=(
                            f"{meta.name}@{meta.version} معتمدةٌ على {allowed} "
                            f"وتُشغَّل على {running_on} باستثناء التجريبي "
                            f"({exception_ref}). النتيجة دليلٌ أماميّ على "
                            f"{running_on}، لا على الفرضية المعلَنة."
                        ),
                        source="Pipeline", at=now,
                    )
                else:
                    self.audit.record(
                        actor=Actor.PIPELINE, action=AuditAction.CONFIG_CHANGE,
                        decision=TIMEFRAME_MISMATCH,
                        reason_ar=(
                            f"{meta.name}@{meta.version} معتمدةٌ على {allowed} "
                            f"وتُشغَّل على {running_on} — لا تُقيَّم. "
                            "اعتمادُ إطارٍ يحتاج دليلاً مُسمّى، لا رأياً."
                        ),
                        source="Pipeline", at=now,
                    )
                    skipped_for_timeframe.append(f"{meta.name}@{meta.version}")
                    continue
            assessment = strategy.assess(
                symbol=symbol, bars=list(bars), quote=quote, now=now
            )
            assessments.append((
                f"{strategy.metadata.name}@{strategy.metadata.version}", assessment,
            ))
            signal = assessment.signal
            if signal is not None:
                break

        if signal is None and skipped_for_timeframe and not assessments:
            # لم تُقيَّم استراتيجيةٌ واحدة: السبب الإعداد لا السوق، ويُقال.
            return self._no_trade(
                "strategy", NO_STRATEGY_FOR_TIMEFRAME,
                f"كل الاستراتيجيات المعتمدة خارج إطار التشغيل {running_on}: "
                f"{'، '.join(skipped_for_timeframe)}. "
                "إمّا يُغيَّر إطار التشغيل، أو يُعتمَد الإطار بدليل — "
                "ولا تُقاس فرضيةٌ على إطارٍ غير إطارها.", now,
            )

        if signal is None:
            # **السبب لا الجملة.** كان يُعاد «لا توجد فرصة مطابقة» وحدها،
            # وهي نفسها سواء كان ADX عند 24.9 أو عند 8. والفرق بينهما هو
            # الفرق بين «انتظري» و«هذه الاستراتيجية لا تناسب هذا السوق».
            detail = " · ".join(
                f"{key}: {a.summary_ar}" for key, a in assessments
            ) or "لم تُشغَّل استراتيجية."
            result = self._no_trade(
                "strategy", "NO_SETUP",
                f"لا فرصة مطابقة. {detail}", now,
            )
            return replace(result, assessments=tuple(assessments))

        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.SIGNAL_GENERATED, decision="SIGNAL",
            reason_ar=signal.rationale_ar, source=f"{signal.strategy_name}@{signal.strategy_version}",
            after=signal.model_dump(mode="json"), at=now,
        )

        # 6) Risk review — **بالنموذج الذي يخصّ هذا الوسيط**
        #
        # كان هذا السطر يستدعي `risk.evaluate` دائماً: مسار أسهم IBKR،
        # بجدول عمولاته وبكميةٍ تُحلّ عكسياً بالسهم — على صفقة CFD في
        # كابيتال. والاقتصاديات المقيسة من كابيتال كانت تُحمَّل في
        # `build_system` وتُعرَض في الشاشة ثم **لا تدخل القرار**.
        if is_cfd(details):
            review = self.cfd_review(signal)
            if review.economics is None:
                # يُسجَّل كغيره: رفضٌ لا يظهر في خط التدقيق رفضٌ لا يُراجَع.
                self.audit.record(
                    actor=Actor.RISK_ENGINE, action=AuditAction.NO_TRADE,
                    decision=review.reason_code or "CFD_ECONOMICS_UNAVAILABLE",
                    reason_ar=review.reason_ar, source="Pipeline.cfd_review", at=now,
                )
                return PipelineResult(
                    Decision.NO_TRADE, review.reason_code, review.reason_ar, "risk",
                    signal=signal, at_utc=now,
                )
            # **النموذج يُمرَّر، لا الحجم.** المحرك يبني سلّم الأحجام
            # القابلة للتنفيذ ويختار الأقرب إلى الهدف تحت السقف الصلب —
            # فلا يُهدَر ثلثا الميزانية عند الكمية الدنيا، ولا تُرفض فرصةٌ
            # لأنها تجاوزت **الهدف** وهي تحت **الحدّ**.
            _model = self.instruments.cost_model_for(signal.symbol)
            _pip = _model.economics.pip_size if _model is not None else None
            decision = self.risk.evaluate_cfd(
                signal=signal, state=state, balances=balances,
                economics=review.economics,
                cost_model=_model,
                stop_distance_pips=(
                    abs(signal.entry_price - signal.stop_price) / _pip if _pip else None
                ),
                take_profit_distance_pips=(
                    abs(signal.take_profit_price - signal.entry_price) / _pip if _pip else None
                ),
                stop_kind=review.economics.stop_kind,
                kill_switch_active=self.kill_switch.is_active, now=now,
            )
        else:
            decision = self.risk.evaluate(
                signal=signal, state=state, balances=balances, schedule=self.schedule,
                assumptions=self.assumptions, fractional_allowed=eligibility.fractional_allowed,
                kill_switch_active=self.kill_switch.is_active, now=now,
            )
        self.audit.record(
            actor=Actor.RISK_ENGINE, action=AuditAction.RISK_DECISION,
            decision=decision.decision.value if decision.approved else (decision.reason_code or "REJECTED"),
            reason_ar=decision.reason_ar, source="RiskEngine",
            after=decision.model_dump(mode="json"), at=now,
        )
        # **الرفضُ يُكتَب صفّاً، لا جملةً في سجلٍّ فقط.**
        #
        # تشخيصُ «لماذا لا يتداول النظام» يحتاج عدَّ الرفض بأسبابه ومراحله.
        # وجدول `risk_decisions` كان مصمَّماً وهدفاً لمفتاحين أجنبيّين، ولا
        # يكتبه أحد — فكان كلُّ سؤالٍ عن الرفض يُجاب بالنصّ لا بالعدد.
        _journal = getattr(self.execution, "journal", None)
        if not decision.approved:
            if _journal is not None:
                _journal.decided(decision, symbol=symbol)
            return PipelineResult(
                Decision.NO_TRADE, decision.reason_code, decision.reason_ar, "risk",
                signal=signal, risk_decision=decision, at_utc=now,
            )

        # 7) حارس الإعداد ثم Order intent + preview + 8) execution
        setup_key = (
            now.date().isoformat(),
            symbol,
            f"{signal.strategy_name}@{signal.strategy_version}",
            bars[-1].start_utc.isoformat() if bars else "",
        )
        if setup_key in self._attempted_setups:
            return self._no_trade(
                "execution", ENTRY_ALREADY_ATTEMPTED,
                f"أُقدِم على هذا الإعداد من قبل: {signal.strategy_name}"
                f"@{signal.strategy_version} على {symbol} لشمعة "
                f"{setup_key[3]}. الحلقة تدور كل دقيقة والشمعة أطول — "
                "وتكرارُ الإشارة ليس فرصةً ثانية.", now,
            )
        self._attempted_setups.add(setup_key)

        intent = build_order_intent(
            signal=signal, decision=decision, trading_day=now.date().isoformat(),
            instrument_snapshot=details.model_dump(mode="json"),
            max_slippage_abs=(quote.spread * D("2")), now=now,
        )
        # القرارُ الموافِق يُكتَب **بعد** بناء النيّة كي يحمل مفتاحها، فيربط
        # `order_intents.risk_decision_id` بقرارٍ بعينه لا بأقربِ قرارٍ زمنياً.
        if _journal is not None:
            _journal.decided(decision, symbol=symbol, intent_key=intent.idempotency_key)

        self.audit.record(
            actor=Actor.PIPELINE, action=AuditAction.ORDER_INTENT_CREATED, decision="CREATED",
            reason_ar=intent.exit_plan_ar, source="Pipeline",
            after=intent.model_dump(mode="json"), related_id=intent.client_order_id, at=now,
        )

        if not self.allow_live_submission and self.broker.is_live:
            return self._no_trade(
                "execution", "LIVE_SUBMISSION_LOCKED",
                "التنفيذ الحقيقي مقفل. النية أُنشئت وسُجّلت ولم تُرسل.", now,
            )

        submission = self.execution.submit(intent)
        if submission.requires_kill_switch:
            trigger = {
                SubmissionOutcome.DUPLICATE_BLOCKED: KillSwitchTrigger.DUPLICATE_ORDER,
                SubmissionOutcome.UNCONFIRMED: KillSwitchTrigger.EXECUTION_CONFIRMATION_FAILED,
                SubmissionOutcome.SIZE_MISMATCH: KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED,
                SubmissionOutcome.SLIPPAGE_EXCEEDED: KillSwitchTrigger.SIZE_EXCEEDS_EXPECTED,
            }.get(submission.outcome, KillSwitchTrigger.STRATEGY_ANOMALY)
            ev = self.kill_switch.trigger(trigger, reason_ar=submission.reason_ar, at=now)
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision=ev.trigger.value, reason_ar=ev.reason_ar, source="Pipeline",
                related_id=intent.client_order_id, at=now,
            )
            return PipelineResult(
                Decision.HALTED, submission.outcome.value, submission.reason_ar, "execution",
                signal=signal, risk_decision=decision, submission=submission, at_utc=now,
            )

        if submission.outcome in (SubmissionOutcome.REJECTED, SubmissionOutcome.PREVIEW_REJECTED):
            return PipelineResult(
                Decision.NO_TRADE, submission.outcome.value, submission.reason_ar, "execution",
                signal=signal, risk_decision=decision, submission=submission, at_utc=now,
            )

        # 9) Reconciliation
        local = list(positions_before)
        if submission.order and submission.order.filled_quantity > 0:
            from ..contracts import Position, Side as _Side

            # ---------------------------------------------------------------
            # **الكمية عندنا تحمل الجهة، لأن كمية الوسيط تحملها.**
            #
            # كان يُكتب `filled_quantity` كما هو — رقمٌ موجب دائماً — ثم
            # تُقارَن بما لدى الوسيط. والوسيط يُبلّغ المركز القصير بإشارة
            # سالبة (‎-0.01‎). فأوّل صفقة بيعٍ تُملأ كانت ستُنتج فوراً:
            #
            #     RECONCILIATION_MISMATCH: لدينا 0.01 ولدى الوسيط -0.01
            #
            # أي: أمرٌ نُفِّذ في السوق، ومركزٌ مفتوح، ونظامٌ يوقف نفسه في
            # اللحظة التالية ظانّاً أن سجلّه اختلف عن حساب الوسيط. وهو لم
            # يختلف — نحن من كتب الرقم بلا جهته.
            #
            # ولم يظهر هذا قط لأن كل صفقةٍ نُفِّذت حتى اليوم كانت شراءً،
            # والموجب يساوي الموجب. صنفُ اليوم نفسه في ثوبه الأخطر: قيمةٌ
            # لا تُقرأ من مصدرها، وتصادف أن تطابقه في الحالة الوحيدة
            # المجرَّبة. والجهة تُقرأ من **الأمر المُنفَّذ** لا من الإشارة،
            # لأن المطابقة تسأل عمّا في السوق لا عمّا نويناه.
            # ---------------------------------------------------------------
            filled = submission.order.filled_quantity
            if submission.order.side is _Side.SELL:
                filled = -filled

            local = list(positions_before) + [
                Position(
                    account_id=balances.account_id, symbol=symbol,
                    quantity=filled,
                    average_cost=submission.order.average_fill_price or signal.entry_price,
                    as_of_utc=now,
                )
            ]
        # **المطابقة تسأل عمّا فعلناه للتوّ، ولا تدّعي دفتراً لا نملكه.**
        #
        # كانت تقارن `local` — وهي المركز الواحد الذي فُتح في هذه الدورة —
        # بحساب الوسيط **كلّه**. فأيُّ مركزٍ ثانٍ مفتوحٍ على أداةٍ أخرى يظهر
        # «غير معروفٍ لدينا» ويرفع قاطع الطوارئ. ومعناه أن سقف «ثلاثة
        # مراكز» في الدستور غير قابلٍ للبلوغ أصلاً: المركز الثاني يوقف
        # النظام في الدورة التي يليه. وقع ذلك على GOLD بعد GBPUSD.
        #
        # ⇒ يُقارَن الرمز المتداوَل وحده. وغيابُ دفتر المراكز المفتوحة
        # عيبٌ مفتوحٌ مسجَّل، ولا يُداوى بادّعاء المطابقة الشاملة.
        recon = reconcile(
            local_positions=local,
            broker_positions=list(self.broker.get_positions(balances.account_id)),
            now=now,
        )
        self.audit.record(
            actor=Actor.SYSTEM, action=AuditAction.RECONCILIATION,
            decision="MATCHED" if recon.matched else "MISMATCH",
            reason_ar="؛ ".join(recon.discrepancies_ar) or "سجلاتنا تطابق حساب الوسيط.",
            source="Reconciliation", at=now,
        )
        if not recon.matched:
            ev = self.kill_switch.trigger(
                KillSwitchTrigger.RECONCILIATION_MISMATCH,
                reason_ar="؛ ".join(recon.discrepancies_ar), at=now,
            )
            self.audit.record(
                actor=Actor.KILL_SWITCH, action=AuditAction.KILL_SWITCH_TRIGGERED,
                decision=ev.trigger.value, reason_ar=ev.reason_ar, source="Pipeline", at=now,
            )
            return PipelineResult(
                Decision.HALTED, "RECONCILIATION_MISMATCH", ev.reason_ar, "reconciliation",
                signal=signal, risk_decision=decision, submission=submission,
                reconciliation_ok=False, at_utc=now,
            )

        return PipelineResult(
            Decision.TRADE, None,
            f"{symbol}: كمية {decision.quantity} بمخاطرة {decision.expected_risk_usd:.2f} دولار.",
            "done", signal=signal, risk_decision=decision, submission=submission,
            reconciliation_ok=True, at_utc=now,
        )
