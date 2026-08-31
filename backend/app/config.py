"""Application settings. LIVE_TRADING is false by default and hard to turn on."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

BrokerMode = Literal[
    "MOCK", "IBKR_PAPER", "IBKR_LIVE", "CAPITAL_DEMO", "CAPITAL_LIVE"
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Maather Autonomous Trader"
    environment: Literal["local", "test"] = "local"

    # ---- The three locks on real money -------------------------------------
    live_trading: bool = Field(default=False, alias="LIVE_TRADING")
    broker_mode: BrokerMode = Field(default="MOCK", alias="BROKER_MODE")
    live_approval_file: str = Field(
        default=str(REPO_ROOT / "secrets" / "live_approval.json"), alias="LIVE_APPROVAL_FILE"
    )

    #: ملف الأسرار على الخادم. على الماك تُقرأ من سلسلة المفاتيح أولاً،
    #: وهذا الملف هو المصدر الوحيد على لينكس حيث لا سلسلة مفاتيح.
    secrets_file: str = Field(
        default=str(REPO_ROOT / "secrets" / "runtime.env"), alias="SECRETS_FILE"
    )

    database_url: str = Field(
        default=f"sqlite:///{REPO_ROOT / 'data' / 'maather.db'}", alias="DATABASE_URL"
    )

    ibkr_host: str = Field(default="127.0.0.1", alias="IBKR_HOST")
    ibkr_port: int = Field(default=4002, alias="IBKR_PORT")  # IB Gateway paper
    ibkr_client_id: int = Field(default=17, alias="IBKR_CLIENT_ID")
    ibkr_account_id: str = Field(default="", alias="IBKR_ACCOUNT_ID")

    display_timezone: str = "Asia/Riyadh"
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    baseline_equity_usd: str = Field(default="150.00", alias="BASELINE_EQUITY_USD")
    risk_mode: Literal[
        "VALIDATION", "LIVE_COMMISSIONING", "CONSERVATIVE_LIVE", "LOCKED_REVIEW"
    ] = Field(
        default="VALIDATION", alias="RISK_MODE"
    )

    @field_validator("broker_mode")
    @classmethod
    def _live_adapter_requires_live_flag(cls, v: str, info):
        return v

    def assert_mode_allowed(self) -> None:
        """
        القفل الرابع: وضع مخاطرة حقيقي يتطلب نفس أقفال التداول الحقيقي.
        لا يمكن تشغيل LIVE_COMMISSIONING أو CONSERVATIVE_LIVE على وسيط وهمي
        أو بدون موافقة موثقة.
        """
        if self.risk_mode in ("VALIDATION", "LOCKED_REVIEW"):
            return
        if not self.live_trading:
            raise RuntimeError(
                f"RISK_MODE={self.risk_mode} يتطلب LIVE_TRADING=true صراحةً."
            )
        if not os.path.exists(self.live_approval_file):
            raise RuntimeError(
                f"RISK_MODE={self.risk_mode} يتطلب ملف موافقة موقّعاً: {self.live_approval_file}"
            )

    def assert_capital_allowed(self) -> None:
        """
        قفل بيئة كابيتال.

        `CAPITAL_DEMO` مسموح دائماً — لا مال فيه.

        `CAPITAL_LIVE` يمرّ من `assert_environment_allowed` في طبقة السلامة،
        وهي تقرأ `LIVE_API_ENABLED` — ثابتٌ مصدريّ لا يُفتح بمتغيّر بيئة.
        نستدعيه هنا صراحةً كي يظهر المنع **عند الإقلاع** بسببٍ مقروء، لا عند
        أوّل طلب شبكة بعد ساعات من العمل.

        وفتح `LIVE_API_ENABLED` لا يفتح التنفيذ: قفل التنفيذ في الناقل مستقلّ،
        ويمنع كل طلب مُعدِّل سواءٌ كانت البيئة تجريبية أو حقيقية.
        """
        if self.broker_mode not in ("CAPITAL_DEMO", "CAPITAL_LIVE"):
            return
        from .brokers.capital.endpoints import CapitalEnvironment
        from .brokers.capital.safety import assert_environment_allowed

        assert_environment_allowed(
            CapitalEnvironment.LIVE
            if self.broker_mode == "CAPITAL_LIVE"
            else CapitalEnvironment.DEMO
        )

    def assert_live_allowed(self) -> None:
        """
        القفل البرمجي: لا يمكن للنظام أن يختار IBKR_LIVE من تلقاء نفسه.
        يجب أن تجتمع: متغير بيئة + ملف موافقة موقّع زمنياً.
        """
        if self.broker_mode != "IBKR_LIVE":
            return
        if not self.live_trading:
            raise RuntimeError(
                "BROKER_MODE=IBKR_LIVE يتطلب LIVE_TRADING=true صراحةً. التداول الحقيقي مقفل."
            )
        if not os.path.exists(self.live_approval_file):
            raise RuntimeError(
                f"ملف موافقة التداول الحقيقي غير موجود: {self.live_approval_file}. التداول الحقيقي مقفل."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
