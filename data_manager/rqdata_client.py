from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
import json
import os
import threading

from backend.core.paths import PROJECT_ROOT


RQDATA_HOST = ("rqdatad-pro.ricequant.com", 16011)
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


EXCHANGE_TO_RQ_SUFFIX = {
    "SSE": "XSHG",
    "SZSE": "XSHE",
    "SHFE": "SHFE",
    "DCE": "DCE",
    "CZCE": "CZCE",
    "CFFEX": "CFFEX",
    "INE": "INE",
    "GFEX": "GFEX",
}


@dataclass(frozen=True)
class RQDataCredentials:
    username: str
    password: str
    source: str


def _read_vt_setting(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _candidate_setting_paths() -> list[Path]:
    paths: list[Path] = []
    env_path = os.getenv("GYRO_VT_SETTING_PATH", "").strip()
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(PROJECT_ROOT / ".vntrader" / "vt_setting.json")
    paths.append(Path.home() / ".vntrader" / "vt_setting.json")
    return paths


def load_credentials() -> RQDataCredentials:
    username = os.getenv("GYRO_RQDATA_USERNAME") or os.getenv("RQDATA_USERNAME") or ""
    password = os.getenv("GYRO_RQDATA_PASSWORD") or os.getenv("RQDATA_PASSWORD") or ""
    if username and password:
        return RQDataCredentials(username=username, password=password, source="environment")

    for path in _candidate_setting_paths():
        settings = _read_vt_setting(path)
        username = str(settings.get("datafeed.username") or "").strip()
        password = str(settings.get("datafeed.password") or "").strip()
        if username and password:
            return RQDataCredentials(username=username, password=password, source=str(path))
    raise RuntimeError("RQData credentials not found. Set GYRO_RQDATA_USERNAME/GYRO_RQDATA_PASSWORD or GYRO_VT_SETTING_PATH.")


def to_rq_symbol(symbol: str, exchange: str) -> str:
    suffix = EXCHANGE_TO_RQ_SUFFIX.get(str(exchange).upper())
    if not suffix:
        raise ValueError(f"Unsupported exchange for RQData: {exchange}")
    return f"{symbol}.{suffix}"


def normalize_datetime(value: str | date | datetime, *, is_end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.max.replace(microsecond=0) if is_end else time.min)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.combine(date.fromisoformat(text), time.max.replace(microsecond=0) if is_end else time.min)


def _frequency(interval: str) -> str:
    normalized = str(interval).lower()
    if normalized in {"1m", "1min", "minute"}:
        return "1m"
    if normalized in {"1d", "d", "day", "daily"}:
        return "1d"
    if normalized in {"1h", "60m", "hour"}:
        return "60m"
    raise ValueError(f"Unsupported interval for RQData download: {interval}")


class RQDataClient:
    name = "rqdata"

    def __init__(self, credentials: RQDataCredentials | None = None) -> None:
        self.credentials = credentials

    def init(self) -> dict[str, Any]:
        global _INITIALIZED
        if _INITIALIZED:
            return {"initialized": True, "credential_source": self.credentials.source if self.credentials else "cached"}
        with _INIT_LOCK:
            if _INITIALIZED:
                return {"initialized": True, "credential_source": self.credentials.source if self.credentials else "cached"}
            credentials = self.credentials or load_credentials()
            import rqdatac

            rqdatac.init(
                credentials.username,
                credentials.password,
                RQDATA_HOST,
                use_pool=True,
                max_pool_size=1,
                auto_load_plugins=False,
            )
            self.credentials = credentials
            _INITIALIZED = True
            return {"initialized": True, "credential_source": credentials.source}

    def query_bars(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        self.init()
        import rqdatac

        rq_symbol = to_rq_symbol(symbol, exchange)
        start = normalize_datetime(start_date, is_end=False)
        end = normalize_datetime(end_date, is_end=True)
        frame = rqdatac.get_price(
            rq_symbol,
            start_date=start,
            end_date=end,
            frequency=_frequency(interval),
            fields=["open", "high", "low", "close", "volume", "total_turnover"],
            adjust_type="none",
        )
        if frame is None or len(frame) == 0:
            return []
        if hasattr(frame, "reset_index"):
            frame = frame.reset_index()
        rows: list[dict[str, Any]] = []
        for item in frame.to_dict(orient="records"):
            dt_value = item.get("datetime") or item.get("date") or item.get("trading_date") or item.get("index")
            if dt_value is None:
                continue
            rows.append(
                {
                    "datetime": datetime.fromisoformat(str(dt_value)).isoformat() if isinstance(dt_value, str) else dt_value.to_pydatetime().isoformat() if hasattr(dt_value, "to_pydatetime") else str(dt_value),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "volume": item.get("volume"),
                    "turnover": item.get("turnover") if item.get("turnover") is not None else item.get("total_turnover"),
                    "open_interest": item.get("open_interest"),
                }
            )
        return rows


def get_default_client() -> RQDataClient:
    return RQDataClient()
