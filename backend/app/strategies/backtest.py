"""
محرّك الاختبار التاريخي — deterministic، واعٍ بالتكاليف، ومحصّن ضد تسرّب المستقبل.

مبادئ غير قابلة للتفاوض:
  1. **لا تسرّب مستقبل.** الاستراتيجية ترى الشموع المغلقة حتى `i` فقط،
     والتنفيذ يقع عند فتح الشمعة `i+1`. لا يمكنها رؤية `i+1` عند القرار.
  2. **لا نتائج مُلفَّقة.** المحرّك لا يولّد بيانات. إن لم تُمرَّر شموع حقيقية،
     لا توجد نتيجة — ويُبلَّغ ذلك صراحةً.
  3. **أسوأ حالة عند الغموض.** إن لامست الشمعة الوقف والهدف معاً،
     نفترض الوقف. لا نمنح أنفسنا فائدة الشك.
  4. **كل التكاليف محسوبة**: السبريد، الانزلاق، التبييت، وتحويل العملة.
  5. **قابلية إعادة الإنتاج**: نفس المدخلات ⇒ نفس `run_id` ونفس الصفقات.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional, Sequence

from ..contracts import Bar, DataSource, Quote, Side, Signal, StopKind
from ..money import D, money, safe_div
from ..risk.capital_costs import CapitalComCostModel, CfdTradeEconomics
from .base import Strategy


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    SESSION_CLOSE = "SESSION_CLOSE"
    END_OF_DATA = "END_OF_DATA"
    AMBIGUOUS_BAR_ASSUMED_STOP = "AMBIGUOUS_BAR_ASSUMED_STOP"


class InsufficientData(RuntimeError):
    """لا توجد بيانات كافية لنتيجة ذات معنى — نُبلغ ولا نخترع."""


@dataclass(frozen=True)
class BacktestConfig:
    """
    إعدادات الاختبار. كلها صريحة — لا قيمة سحرية مخفية.
    """

    size: Decimal
    stop_distance_pips: Decimal
    take_profit_distance_pips: Decimal
    stop_kind: StopKind = StopKind.NORMAL
    allow_overnight: bool = False
    max_bars_in_trade: int = 24
    min_trades_for_conclusion: int = 30

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {k: str(v) for k, v in asdict(self).items()}, sort_keys=True
            ).encode()
        ).hexdigest()[:16]


@dataclass(frozen=True)
class BacktestTrade:
    index_in: int
    index_out: int
    entered_at_utc: datetime
    exited_at_utc: datetime
    side: Side
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal
    stop_price: Decimal
    take_profit_price: Decimal
    exit_reason: ExitReason
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    nights_held: int
    rationale_ar: str

    @property
    def is_win(self) -> bool:
        return self.net_pnl > 0


@dataclass
class BacktestResult:
    run_id: str
    strategy_name: str
    strategy_version: str
    config_digest: str
    bars_count: int
    first_bar_utc: Optional[datetime]
    last_bar_utc: Optional[datetime]
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[Decimal] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # --- مقاييس ---------------------------------------------------------
    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.is_win)

    @property
    def losses(self) -> int:
        return self.trade_count - self.wins

    @property
    def net_pnl(self) -> Decimal:
        return sum((t.net_pnl for t in self.trades), D("0"))

    @property
    def gross_profit(self) -> Decimal:
        return sum((t.net_pnl for t in self.trades if t.net_pnl > 0), D("0"))

    @property
    def gross_loss(self) -> Decimal:
        return sum((-t.net_pnl for t in self.trades if t.net_pnl < 0), D("0"))

    @property
    def profit_factor(self) -> Optional[Decimal]:
        if self.gross_loss == 0:
            return None  # لا نعيد "لا نهاية" — نعيد غير معرّف
        return self.gross_profit / self.gross_loss

    @property
    def expectancy(self) -> Optional[Decimal]:
        if not self.trades:
            return None
        return self.net_pnl / D(self.trade_count)

    @property
    def win_rate(self) -> Optional[Decimal]:
        if not self.trades:
            return None
        return D(self.wins) / D(self.trade_count)

    @property
    def max_drawdown(self) -> Decimal:
        peak = D("0")
        running = D("0")
        worst = D("0")
        for trade in self.trades:
            running += trade.net_pnl
            peak = max(peak, running)
            worst = min(worst, running - peak)
        return -worst

    @property
    def largest_win(self) -> Decimal:
        return max((t.net_pnl for t in self.trades), default=D("0"))

    @property
    def dependence_on_best_trade(self) -> Optional[Decimal]:
        """
        كم من الربح الصافي يأتي من أفضل صفقة واحدة.
        قيمة عالية = النتيجة تعتمد على حدث استثنائي لا على أفضلية حقيقية.
        """
        if self.net_pnl <= 0:
            return None
        return safe_div(self.largest_win, self.net_pnl, D("0"))

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "strategy": f"{self.strategy_name}@{self.strategy_version}",
            "config_digest": self.config_digest,
            "bars": self.bars_count,
            "first_bar_utc": self.first_bar_utc.isoformat() if self.first_bar_utc else None,
            "last_bar_utc": self.last_bar_utc.isoformat() if self.last_bar_utc else None,
            "trades": self.trade_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": str(self.win_rate) if self.win_rate is not None else None,
            "net_pnl": f"{self.net_pnl:.2f}",
            "expectancy": f"{self.expectancy:.4f}" if self.expectancy is not None else None,
            "profit_factor": (
                f"{self.profit_factor:.2f}" if self.profit_factor is not None else "غير معرّف"
            ),
            "max_drawdown": f"{self.max_drawdown:.2f}",
            "dependence_on_best_trade": (
                f"{self.dependence_on_best_trade:.2f}"
                if self.dependence_on_best_trade is not None
                else None
            ),
            "warnings": list(self.warnings),
        }


class Backtester:
    """
    محرّك بسيط ومحافظ. لا يحاول محاكاة دفتر الأوامر — يحاكي فقط
    ما يمكن الدفاع عنه: الدخول بسعر الطلب مع انزلاق، والخروج عند الوقف أو الهدف.
    """

    def __init__(self, cost_model: CapitalComCostModel, config: BacktestConfig) -> None:
        self.cost_model = cost_model
        self.config = config

    # ------------------------------------------------------------------
    @staticmethod
    def _bars_digest(bars: Sequence[Bar]) -> str:
        payload = [
            [b.start_utc.isoformat(), str(b.open), str(b.high), str(b.low), str(b.close)]
            for b in bars
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def _economics(self, stop_pips: Decimal, tp_pips: Decimal, entry: Decimal, nights: int):
        return self.cost_model.estimate(
            size=self.config.size,
            entry_price=entry,
            stop_distance_pips=stop_pips,
            take_profit_distance_pips=tp_pips,
            stop_kind=self.config.stop_kind,
            nights_held=nights,
        )

    @staticmethod
    def _nights_between(start: datetime, end: datetime) -> int:
        return max(0, (end.date() - start.date()).days)

    # ------------------------------------------------------------------
    def run(
        self,
        strategy: Strategy,
        bars: Sequence[Bar],
        *,
        symbol: Optional[str] = None,
    ) -> BacktestResult:
        bars = list(bars)
        if not bars:
            raise InsufficientData(
                "لا توجد شموع. المحرّك لا يولّد بيانات — وفّري بيانات تاريخية حقيقية."
            )
        symbol = symbol or bars[0].symbol
        min_bars = strategy.metadata.min_bars_required
        if len(bars) < min_bars + 2:
            raise InsufficientData(
                f"عدد الشموع {len(bars)} أقل من الحد الأدنى {min_bars + 2} لهذه الاستراتيجية."
            )

        run_id = hashlib.sha256(
            "|".join(
                [
                    strategy.metadata.name,
                    strategy.metadata.version,
                    self.config.digest(),
                    self._bars_digest(bars),
                    self.cost_model.economics.epic,
                ]
            ).encode()
        ).hexdigest()[:16]

        result = BacktestResult(
            run_id=run_id,
            strategy_name=strategy.metadata.name,
            strategy_version=strategy.metadata.version,
            config_digest=self.config.digest(),
            bars_count=len(bars),
            first_bar_utc=bars[0].start_utc,
            last_bar_utc=bars[-1].start_utc,
        )

        pip = self.cost_model.economics.pip_size
        spread = self.cost_model.assumptions.spread_price
        slippage_price = self.cost_model.assumptions.slippage_reserve_pips * pip

        i = min_bars
        equity = D("0")
        while i < len(bars) - 1:
            visible = bars[: i + 1]          # الشموع المغلقة فقط
            last_close = visible[-1]
            quote = Quote(
                symbol=symbol,
                bid=last_close.close,
                ask=last_close.close + spread,
                last=last_close.close,
                timestamp_utc=last_close.start_utc,
                source=DataSource.HISTORICAL,
                received_at_utc=last_close.start_utc,
            )
            signal = strategy.evaluate(
                symbol=symbol, bars=visible, quote=quote, now=last_close.start_utc
            )
            if signal is None:
                i += 1
                continue

            # التنفيذ عند فتح الشمعة التالية — لا يمكن للاستراتيجية رؤيتها.
            entry_bar = bars[i + 1]
            long = signal.side is Side.BUY

            # ---------------------------------------------------------------
            # **الوقف والهدف من الإشارة نفسها، لا من إعدادٍ ثابت.**
            #
            # كان المحرّك يفرض وقفاً ثابتاً (٣٠ نقطة) وهدفاً ثابتاً على كل
            # إشارة، مهما قالت الاستراتيجية. وكل استراتيجياتنا تشتقّ وقفها
            # من ATR — أي من تقلّب السوق ساعتَه.
            #
            # ⇒ كان الاختبار يقيس **استراتيجيةً أخرى** تحمل الاسم نفسه:
            # نفس شروط الدخول، وخروجٌ مختلف تماماً. ونتيجةٌ من ذلك لا تقول
            # شيئاً عمّا سيقع في السوق، لا سلباً ولا إيجاباً.
            #
            # والانزلاق يُطبَّق في الجهة التي تضرّ: يرفع سعر الشراء ويخفض
            # سعر البيع. وتطبيقه في جهةٍ واحدة يجعل نصف الصفقات تربح منه.
            # ---------------------------------------------------------------
            if long:
                entry_price = entry_bar.open + spread + slippage_price
            else:
                entry_price = entry_bar.open - spread - slippage_price
            stop_price = signal.stop_price
            target_price = signal.take_profit_price

            stop_pips = self.cost_model.price_to_pips(abs(entry_price - stop_price))
            target_pips = self.cost_model.price_to_pips(abs(target_price - entry_price))

            exit_index = None
            exit_price = None
            reason = ExitReason.END_OF_DATA
            for j in range(i + 1, min(len(bars), i + 1 + self.config.max_bars_in_trade)):
                bar = bars[j]
                # **الاتجاه يقلب معنى «لُمس».** في البيع يقع الوقف فوق الدخول
                # فيُلمس بالارتفاع، والهدف تحته فيُلمس بالانخفاض. وقراءةُ
                # صفقة بيعٍ بمنطق الشراء تعكس كل ربحٍ وخسارة فيها.
                hit_stop = (bar.low <= stop_price) if long else (bar.high >= stop_price)
                hit_target = (bar.high >= target_price) if long else (bar.low <= target_price)
                if hit_stop and hit_target:
                    exit_index, exit_price = j, stop_price
                    reason = ExitReason.AMBIGUOUS_BAR_ASSUMED_STOP
                    break
                if hit_stop:
                    exit_index, exit_price = j, stop_price
                    reason = ExitReason.STOP_LOSS
                    break
                if hit_target:
                    exit_index, exit_price = j, target_price
                    reason = ExitReason.TAKE_PROFIT
                    break
                if not self.config.allow_overnight and bar.start_utc.date() != entry_bar.start_utc.date():
                    exit_index, exit_price = j, bar.close
                    reason = ExitReason.SESSION_CLOSE
                    break

            if exit_index is None:
                exit_index = min(len(bars) - 1, i + self.config.max_bars_in_trade)
                exit_price = bars[exit_index].close
                reason = ExitReason.END_OF_DATA

            nights = (
                self._nights_between(entry_bar.start_utc, bars[exit_index].start_utc)
                if self.config.allow_overnight
                else 0
            )
            economics = self._economics(stop_pips, target_pips, entry_price, nights)
            units = self.config.size * self.cost_model.economics.lot_size
            gross = money(
                ((exit_price - entry_price) if long else (entry_price - exit_price)) * units
            )
            costs = money(
                economics.spread_cost
                + economics.guaranteed_stop_premium
                + economics.overnight_cost
                + economics.conversion_cost
            )
            net = money(gross - costs)
            equity += net
            result.equity_curve.append(equity)

            result.trades.append(
                BacktestTrade(
                    index_in=i + 1,
                    index_out=exit_index,
                    entered_at_utc=entry_bar.start_utc,
                    exited_at_utc=bars[exit_index].start_utc,
                    side=Side.BUY,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    size=self.config.size,
                    stop_price=stop_price,
                    take_profit_price=target_price,
                    exit_reason=reason,
                    gross_pnl=gross,
                    costs=costs,
                    net_pnl=net,
                    nights_held=nights,
                    rationale_ar=signal.rationale_ar,
                )
            )
            i = exit_index + 1  # لا تداخل بين الصفقات — مركز واحد فقط

        if result.trade_count < self.config.min_trades_for_conclusion:
            result.warnings.append(
                f"عدد الصفقات {result.trade_count} أقل من الحد الأدنى "
                f"{self.config.min_trades_for_conclusion} — النتيجة غير كافية لأي استنتاج."
            )
        if self.cost_model.economics.is_provisional:
            result.warnings.append(
                "خصائص الأداة مبدئية وليست مُكتشَفة من الوسيط — النتائج تقديرية."
            )
        ambiguous = sum(
            1 for t in result.trades if t.exit_reason is ExitReason.AMBIGUOUS_BAR_ASSUMED_STOP
        )
        if ambiguous:
            result.warnings.append(
                f"{ambiguous} صفقة لامست الوقف والهدف في الشمعة نفسها — احتُسبت وقفاً (أسوأ حالة)."
            )
        return result


# ---------------------------------------------------------------------------
# Walk-forward و out-of-sample
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WalkForwardFold:
    index: int
    in_sample: tuple[int, int]
    out_of_sample: tuple[int, int]


@dataclass
class WalkForwardResult:
    folds: list[WalkForwardFold]
    in_sample: list[BacktestResult]
    out_of_sample: list[BacktestResult]
    warnings: list[str] = field(default_factory=list)

    @property
    def out_of_sample_net(self) -> Decimal:
        return sum((r.net_pnl for r in self.out_of_sample), D("0"))

    @property
    def in_sample_net(self) -> Decimal:
        return sum((r.net_pnl for r in self.in_sample), D("0"))

    @property
    def out_of_sample_positive_folds(self) -> int:
        return sum(1 for r in self.out_of_sample if r.net_pnl > 0)

    @property
    def degradation_ratio(self) -> Optional[Decimal]:
        """
        نسبة أداء خارج العيّنة إلى داخلها. قريبة من 1 = استقرار،
        وقريبة من الصفر أو سالبة = ملاءمة مفرطة.
        """
        if self.in_sample_net <= 0:
            return None
        return safe_div(self.out_of_sample_net, self.in_sample_net, D("0"))

    def summary(self) -> dict:
        return {
            "folds": len(self.folds),
            "in_sample_net": f"{self.in_sample_net:.2f}",
            "out_of_sample_net": f"{self.out_of_sample_net:.2f}",
            "out_of_sample_positive_folds": self.out_of_sample_positive_folds,
            "degradation_ratio": (
                f"{self.degradation_ratio:.2f}" if self.degradation_ratio is not None else None
            ),
            "warnings": list(self.warnings),
        }


def split_walk_forward(
    total_bars: int, *, folds: int = 4, in_sample_ratio: Decimal = D("0.7")
) -> list[WalkForwardFold]:
    """
    تقسيم زمني متتابع بلا خلط. لا يُسمح بأن تسبق عيّنة الاختبار عيّنة التدريب.
    """
    if folds < 1:
        raise ValueError("عدد الطيّات يجب أن يكون 1 على الأقل.")
    window = total_bars // folds
    if window < 10:
        raise InsufficientData(
            f"طول الطيّة {window} شمعة غير كافٍ — قلّلي عدد الطيّات أو زيدي البيانات."
        )
    out: list[WalkForwardFold] = []
    for k in range(folds):
        start = k * window
        end = start + window if k < folds - 1 else total_bars
        cut = start + int((end - start) * float(in_sample_ratio))
        out.append(
            WalkForwardFold(index=k, in_sample=(start, cut), out_of_sample=(cut, end))
        )
    return out


def run_walk_forward(
    backtester: Backtester,
    strategy: Strategy,
    bars: Sequence[Bar],
    *,
    folds: int = 4,
    in_sample_ratio: Decimal = D("0.7"),
) -> WalkForwardResult:
    bars = list(bars)
    splits = split_walk_forward(len(bars), folds=folds, in_sample_ratio=in_sample_ratio)
    in_sample: list[BacktestResult] = []
    out_of_sample: list[BacktestResult] = []
    warnings: list[str] = []

    for fold in splits:
        for label, (lo, hi), bucket in (
            ("in", fold.in_sample, in_sample),
            ("out", fold.out_of_sample, out_of_sample),
        ):
            segment = bars[lo:hi]
            try:
                bucket.append(backtester.run(strategy, segment))
            except InsufficientData as exc:
                warnings.append(f"الطيّة {fold.index} ({label}): {exc}")

    return WalkForwardResult(
        folds=splits, in_sample=in_sample, out_of_sample=out_of_sample, warnings=warnings
    )


# ---------------------------------------------------------------------------
# استقرار المعاملات
# ---------------------------------------------------------------------------

@dataclass
class ParameterStabilityReport:
    results: dict[str, dict]
    metric: str

    @property
    def values(self) -> list[Decimal]:
        out = []
        for entry in self.results.values():
            raw = entry.get(self.metric)
            if raw not in (None, "غير معرّف"):
                out.append(D(raw))
        return out

    @property
    def positive_share(self) -> Optional[Decimal]:
        values = self.values
        if not values:
            return None
        return D(sum(1 for v in values if v > 0)) / D(len(values))

    @property
    def spread(self) -> Optional[Decimal]:
        values = self.values
        if len(values) < 2:
            return None
        return max(values) - min(values)

    def is_stable(self, *, min_positive_share: Decimal = D("0.7")) -> bool:
        """
        مستقرّة = أغلب النقاط المجاورة في شبكة المعاملات تعطي نتيجة موجبة.
        قمّة معزولة وسط خسائر = ملاءمة مفرطة لا أفضلية.
        """
        share = self.positive_share
        return share is not None and share >= min_positive_share


def analyse_parameter_stability(
    build_backtester: Callable[[BacktestConfig], Backtester],
    strategy: Strategy,
    bars: Sequence[Bar],
    configs: Sequence[BacktestConfig],
    *,
    metric: str = "net_pnl",
) -> ParameterStabilityReport:
    results: dict[str, dict] = {}
    for config in configs:
        backtester = build_backtester(config)
        try:
            outcome = backtester.run(strategy, bars)
        except InsufficientData as exc:
            results[config.digest()] = {"error": str(exc)}
            continue
        results[config.digest()] = outcome.summary()
    return ParameterStabilityReport(results=results, metric=metric)
