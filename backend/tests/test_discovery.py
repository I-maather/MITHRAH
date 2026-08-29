"""أمر الاكتشاف — يثبت أنه لا يستطيع لمس أي endpoint مُعدِّل."""
from __future__ import annotations

import json

import pytest

from app.brokers.capital.endpoints import PATH_POSITIONS, PATH_SESSION
from app.brokers.capital.safety import ExecutionLocked
from app.cli import build_parser, main
from app.discovery.capital_discovery import (
    DISCOVERY_EPICS,
    EXECUTION_EPICS,
    FORBIDDEN_OPERATIONS,
    DiscoveryViolation,
    assert_read_only_session,
    run_discovery,
    write_reports,
)
from app.money import D
from tests.capital_fixtures import (
    build_adapter,
    build_transport,
    eurusd_market_body,
    generic_market_body,
)


def all_markets():
    return {
        "EURUSD": eurusd_market_body(),
        "GBPUSD": generic_market_body("GBPUSD", bid=1.2700, offer=1.27008),
        "USDJPY": generic_market_body("USDJPY", bid=150.10, offer=150.11),
        "GOLD": generic_market_body("GOLD", type_="COMMODITIES", bid=2400.0, offer=2400.4),
    }


def discovered(**kwargs):
    adapter, guarded, fixture = build_adapter(build_transport(markets=all_markets()))
    adapter.connect()
    report = run_discovery(adapter, **kwargs)
    return report, adapter, guarded, fixture


# --- القوائم ---------------------------------------------------------------

def test_discovery_allowlist_matches_the_specification():
    assert DISCOVERY_EPICS == ("EURUSD", "GBPUSD", "USDJPY", "GOLD")


def test_execution_allowlist_is_eurusd_only():
    assert EXECUTION_EPICS == ("EURUSD",)


# --- قراءة فقط ---------------------------------------------------------------

def test_discovery_only_issues_read_operations():
    _report, _adapter, guarded, _fixture = discovered()
    for method, path in guarded.sent_operations:
        if (method, path) == ("POST", PATH_SESSION):
            continue
        assert method == "GET", f"عملية غير قراءة: {method} {path}"
    assert_read_only_session(guarded)


def test_forbidden_operations_list_covers_every_mutating_endpoint():
    paths = {path for _method, path in FORBIDDEN_OPERATIONS}
    assert "/api/v1/positions" in paths
    assert "/api/v1/workingorders" in paths
    assert "/api/v1/accounts/preferences" in paths
    assert "/api/v1/accounts/topUp" in paths


def test_read_only_assertion_fails_if_a_mutating_operation_was_sent():
    _report, _adapter, guarded, _fixture = discovered()
    guarded.sent_operations.append(("POST", PATH_POSITIONS))
    with pytest.raises(DiscoveryViolation, match="عملية ممنوعة"):
        assert_read_only_session(guarded)


def test_discovery_cannot_reach_a_mutating_endpoint_even_if_asked():
    _report, adapter, guarded, fixture = discovered()
    before = len(fixture.calls)
    with pytest.raises(ExecutionLocked):
        guarded.send("POST", adapter.session.base_url + PATH_POSITIONS, headers={}, json={})
    assert len(fixture.calls) == before


def test_live_environment_is_refused_by_the_cli():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["capital-discover", "--environment", "live"])


def _cli_commands() -> set[str]:
    parser = build_parser()
    actions = [a for a in parser._actions if hasattr(a, "choices") and a.choices]
    commands: set[str] = set()
    for action in actions:
        if isinstance(action.choices, dict):
            commands |= set(action.choices)
    return commands


def test_cli_exposes_only_read_only_commands():
    """
    قائمة بيضاء صريحة. إضافة أمر جديد تتطلب تعديل هذا الاختبار عمداً —
    وهذا هو الغرض: ألا يتسلّل أمر تنفيذي بلا قرار واعٍ.

    `capital-auth-probe` تشخيصي: يصادق فقط (`POST /session`) ولا يلمس
    مركزاً ولا أمراً ولا تفضيلاً.

    `capital-live-discover` يمسّ الحساب الحقيقي **قراءةً فقط**، بقائمة بيضاء
    مفروضة على مستوى HTTP، ولا يعمل بلا إقرار صريح من المالكة.

    `capital-live-spread-sample` يقيس السبريد: مصادقة واحدة ثم
    `GET /markets/EURUSD` متكرر. **لا يطلب رصيداً ولا تفضيلات ولا مراكز.**

    `provider-probe` و`provider-status` يخصّان مزوّدي البيانات لا الوسيط:
    الأول طلب قراءة واحد لإثبات قدرة خطة، والثاني عرض حالة إعداد **بلا كشف
    أي قيمة**. لا صلة لأيٍّ منهما بـCapital.com.
    """
    assert _cli_commands() == {
        "capital-discover",
        "capital-live-discover",
        "capital-live-spread-sample",
        "capital-auth-probe",
        "provider-probe",
        "provider-status",
        "secrets-status",
        "constitution",
    }


def test_no_cli_command_name_suggests_execution():
    forbidden = ("order", "trade", "buy", "sell", "position", "execute",
                 "submit", "close", "topup", "top-up", "deposit")
    for command in _cli_commands():
        lowered = command.lower()
        for word in forbidden:
            assert word not in lowered, f"أمر يوحي بالتنفيذ: {command}"


# --- محتوى التقرير -----------------------------------------------------------

def test_report_contains_every_required_field():
    report, _a, _g, _f = discovered()
    payload = report.to_json()
    assert payload["environment"] == "demo"
    assert payload["read_only"] is True
    assert payload["account"]["masked_id"] == "****3456"
    assert payload["account"]["currency"] == "USD"
    assert payload["account"]["hedging_mode"] is False
    assert payload["generated_at_riyadh"]
    assert payload["generated_at_utc"]
    assert payload["constitution_version"] == "0.2.0"

    eurusd = next(m for m in payload["markets"] if m["epic"] == "EURUSD")
    for key in (
        "market_status", "min_deal_size", "min_size_increment", "margin_factor",
        "min_stop_or_profit_distance", "min_guaranteed_stop_distance",
        "guaranteed_stop_allowed", "bid", "offer", "spread", "pip_size", "overnight_fee",
    ):
        assert key in eurusd, key


def test_report_includes_worked_examples_at_25_50_75_pips():
    report, _a, _g, _f = discovered()
    distances = [e["stop_distance_pips"] for e in report.worked_examples]
    assert distances == ["25", "50", "75"]
    for example in report.worked_examples:
        assert example["notional_exposure"] != example["margin_required"]
        assert example["notional_exposure"] != example["all_in_risk_at_stop"]


def test_worked_examples_flag_which_stops_fit_the_caps():
    report, _a, _g, _f = discovered()
    by_pips = {e["stop_distance_pips"]: e for e in report.worked_examples}
    assert by_pips["25"]["within_050"] == "✅"
    assert by_pips["50"]["within_075"] == "✅"
    assert by_pips["75"]["within_075"] == "❌"


def test_report_records_discrepancies_from_public_site_assumptions():
    markets = all_markets()
    markets["EURUSD"] = eurusd_market_body(min_deal_size=500.0, margin_factor=3.33)
    adapter, _g, _f = build_adapter(build_transport(markets=markets))
    adapter.connect()
    report = run_discovery(adapter, fetch_candles=False)
    joined = " ".join(report.discrepancies)
    assert "أدنى كمية فعلية" in joined
    assert "معامل الهامش الفعلي" in joined


def test_report_notes_when_guaranteed_stop_is_unavailable():
    markets = all_markets()
    markets["EURUSD"] = eurusd_market_body(guaranteed_stop=False)
    adapter, _g, _f = build_adapter(build_transport(markets=markets))
    adapter.connect()
    report = run_discovery(adapter, fetch_candles=False)
    assert any("الوقف المضمون غير متاح" in d for d in report.discrepancies)


def test_report_survives_a_failing_instrument_and_records_the_error():
    markets = all_markets()
    del markets["GOLD"]
    adapter, _g, _f = build_adapter(build_transport(markets=markets))
    adapter.connect()
    report = run_discovery(adapter, fetch_candles=False)
    gold = next(m for m in report.markets if m.epic == "GOLD")
    assert gold.ok is False
    assert gold.error_ar


def test_markdown_report_renders_the_three_separate_values():
    report, _a, _g, _f = discovered()
    markdown = report.to_markdown()
    assert "التعرّض" in markdown
    assert "الهامش" in markdown
    assert "الخسارة الكلية" in markdown
    assert "قراءة فقط" in markdown


def test_reports_are_written_to_disk(tmp_path):
    report, _a, _g, _f = discovered()
    json_path, md_path = write_reports(
        report, json_path=tmp_path / "d.json", markdown_path=tmp_path / "D.md"
    )
    payload = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    assert payload["read_only"] is True
    assert (tmp_path / "D.md").read_text(encoding="utf-8").startswith("# Capital.com Demo Discovery")


def test_candles_count_is_recorded_when_requested():
    report, _a, _g, _f = discovered(fetch_candles=True)
    eurusd = next(m for m in report.markets if m.epic == "EURUSD")
    assert eurusd.candles_available == 5
