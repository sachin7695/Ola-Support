# tools_ola.py
from __future__ import annotations
import random
from datetime import date as _date
from typing import Dict, Any, Optional
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams


# Cache the last verified number (per-process simple cache).
_LAST_VERIFIED_MSISDN: str | None = None

def _set_last_msisdn(msisdn: str) -> None:
    global _LAST_VERIFIED_MSISDN
    _LAST_VERIFIED_MSISDN = msisdn

def _resolve_msisdn_from_args_or_cache(args: dict) -> str | None:
    raw = args.get("phone_number")
    if raw:
        return normalize_msisdn(raw)
    return _LAST_VERIFIED_MSISDN


# Mock “datastores”
DRIVERS_DB: Dict[str, Dict[str, Any]] = {
    "+919876543210": {"name": "Ramesh", "blocked": False, "registered": True, "city": "Bengaluru", "rating": 4.82},
    "+919911223344": {"name": "Suresh", "blocked": True,  "registered": True, "city": "Delhi", "rating": 4.55},
}

ACCOUNT_HEALTH_DB = {
    "+919876543210": {"docs_pending": [], "bgv_status": "clear", "strikes": 0, "deactivation_reason": None},
    "+919911223344": {"docs_pending": ["RC"], "bgv_status": "pending", "strikes": 2, "deactivation_reason": "compliance_hold"},
}

ONLINE_STATUS_DB = {
    "+919876543210": {"last_online_at": "2025-10-24T09:10:00+05:30", "online_hours_today": 2.3, "app_version": "5.14.2"},
    "+919911223344": {"last_online_at": "2025-10-24T07:05:00+05:30", "online_hours_today": 0.4, "app_version": "5.10.0"},
}

WALLET_DB = {
    "+919876543210": {"wallet_balance": 732.50, "next_payout_date": "2025-10-26", "holds": []},
    "+919911223344": {"wallet_balance": 12.0,   "next_payout_date": "2025-10-25", "holds": ["KYC hold"]},
}

INCENTIVES_DB = {
    ("Bengaluru","2025-10-24"): {"surge_multiplier": 1.0, "quest_bonus": "3 rides → ₹150", "slots_remaining": True},
    ("Delhi","2025-10-24"):     {"surge_multiplier": 1.4, "quest_bonus": "5 rides → ₹300", "slots_remaining": False},
}

def _mock_supply_demand(lat: float, lon: float) -> dict:
    return {
        "demand_index": 0.42,
        "median_wait_mins": 11,
        "hotspots": [
            {"name": "Majestic Bus Stand", "lat": 12.978, "lon": 77.571, "eta_mins": 14},
            {"name": "Orion Mall",         "lat": 13.011, "lon": 77.555, "eta_mins": 18},
        ],
        "suggestion": "Peenya taraf move kariye; aaj wahan demand zyada hai."
    }


# Helpers
def normalize_msisdn(raw: str, default_cc: str = "+91") -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10:
        return f"{default_cc}{digits}"
    return f"+{digits}" if not raw.startswith("+") else raw


# Schemas
verify_driver_number_schema = FunctionSchema(
    name="verify_driver_number",
    description="Verify driver's phone; return registration + block status.",
    properties={
        "phone_number": {"type": "string", "description": "Spoken phone number"},
        "country_code": {"type": "string", "description": "Default '+91'", "default": "+91"},
    },
    required=["phone_number"],
)

get_driver_account_health_schema = FunctionSchema(
    name="get_driver_account_health",
    description="Fetch compliance/account health after number verification.",
    properties={"phone_number": {"type": "string", "description": "Optional; falls back to last verified number."}},
    required=[],
)

# Add a new purpose 'docs_update' for sending RC/KYC steps
push_device_reauth_schema = FunctionSchema(
    name="push_device_reauth",
    description="Send OTP or docs-update link to the verified number.",
    properties={
        "phone_number": {"type": "string", "description": "Optional; falls back to last verified number."},
        "purpose": {"type": "string", "enum": ["reauth","update","docs_update"]},
    },
    required=["purpose"],
)


check_app_online_status_schema = FunctionSchema(
    name="check_app_online_status",
    description="Check last-online, online-hours today, and app version.",
    properties={"phone_number": {"type": "string"}},
    required=["phone_number"],
)

get_supply_demand_snapshot_schema = FunctionSchema(
    name="get_supply_demand_snapshot",
    description="Given lat/lon, return demand index, wait estimate, hotspots, and a suggestion.",
    properties={
        "lat": {"type": "number"},
        "lon": {"type": "number"},
        "city": {"type": "string", "description": "Optional city hint"},
    },
    required=["lat","lon"],
)

fetch_wallet_and_payouts_schema = FunctionSchema(
    name="fetch_wallet_and_payouts",
    description="Driver wallet balance, next payout date, and payout holds.",
    properties={"phone_number": {"type": "string"}},
    required=["phone_number"],
)

get_incentives_today_schema = FunctionSchema(
    name="get_incentives_today",
    description="Returns surge/quests availability for city + date.",
    properties={
        "city": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD (defaults today)"},
    },
    required=["city"],
)

push_device_reauth_schema = FunctionSchema(
    name="push_device_reauth",
    description="Send OTP/app-update link to the verified number.",
    properties={"phone_number": {"type": "string"}, "purpose": {"type": "string", "enum": ["reauth","update"]}},
    required=["phone_number","purpose"],
)

create_support_ticket_schema = FunctionSchema(
    name="create_support_ticket",
    description="Create a support ticket and return ticket_id.",
    properties={
        "phone_number": {"type": "string"},
        "category": {"type": "string", "enum": ["account_block","docs_pending","payout_hold","app_issue","other"]},
        "summary": {"type": "string"},
        "severity": {"type": "string", "enum": ["low","medium","high"], "default": "low"}
    },
    required=["phone_number","category","summary"],
)


# Implementations (async)

def make_verify_driver_number():
    async def verify_driver_number(params: FunctionCallParams):
        msisdn = normalize_msisdn(
            params.arguments["phone_number"],
            params.arguments.get("country_code", "+91"),
        )
        rec = DRIVERS_DB.get(msisdn)
        _set_last_msisdn(msisdn)  # ✅ cache

        await params.result_callback({
            "normalized_number": msisdn,
            "is_registered": bool(rec and rec.get("registered")),
            "is_blocked": bool(rec and rec.get("blocked")),
            "city": rec.get("city") if rec else None,
            "display_name": rec.get("name") if rec else None,
            "rating": rec.get("rating") if rec else None,
        })
    return verify_driver_number


def make_get_driver_account_health():
    async def get_driver_account_health(params: FunctionCallParams):
        msisdn = _resolve_msisdn_from_args_or_cache(params.arguments)
        if not msisdn:
            await params.result_callback({"status":"error","reason":"missing_phone_number"})
            return
        rec = ACCOUNT_HEALTH_DB.get(msisdn, {})
        await params.result_callback({
            "docs_pending": rec.get("docs_pending", []),
            "bgv_status": rec.get("bgv_status", "unknown"),
            "strikes": rec.get("strikes", 0),
            "deactivation_reason": rec.get("deactivation_reason"),
        })
    return get_driver_account_health

def make_push_device_reauth():
    async def push_device_reauth(params: FunctionCallParams):
        msisdn = _resolve_msisdn_from_args_or_cache(params.arguments)
        if not msisdn:
            await params.result_callback({"status":"error","reason":"missing_phone_number"})
            return
        purpose = params.arguments["purpose"]
        import random
        token = f"OTP-{random.randint(100000,999999)}"
        await params.result_callback({
            "sent": True, "msisdn": msisdn, "purpose": purpose, "token_hint": token[:3]+"***"
        })
    return push_device_reauth


def make_check_app_online_status():
    async def check_app_online_status(params: FunctionCallParams):
        msisdn = normalize_msisdn(params.arguments["phone_number"])
        info = ONLINE_STATUS_DB.get(msisdn, {})
        await params.result_callback({
            "last_online_at": info.get("last_online_at"),
            "online_hours_today": info.get("online_hours_today", 0.0),
            "app_version": info.get("app_version", "unknown"),
            "needs_update": info.get("app_version","0") < "5.12.0",
        })
    return check_app_online_status

def make_get_supply_demand_snapshot():
    async def get_supply_demand_snapshot(params: FunctionCallParams):
        lat = float(params.arguments["lat"]); lon = float(params.arguments["lon"])
        snap = _mock_supply_demand(lat, lon)
        await params.result_callback(snap)
    return get_supply_demand_snapshot

def make_fetch_wallet_and_payouts():
    async def fetch_wallet_and_payouts(params: FunctionCallParams):
        msisdn = normalize_msisdn(params.arguments["phone_number"])
        row = WALLET_DB.get(msisdn, {})
        await params.result_callback({
            "wallet_balance": row.get("wallet_balance", 0.0),
            "next_payout_date": row.get("next_payout_date"),
            "holds": row.get("holds", []),
        })
    return fetch_wallet_and_payouts

def make_get_incentives_today():
    async def get_incentives_today(params: FunctionCallParams):
        city = params.arguments["city"]
        d = params.arguments.get("date") or str(_date.today())
        info = INCENTIVES_DB.get((city, d), {"surge_multiplier": 1.0, "quest_bonus": None, "slots_remaining": False})
        await params.result_callback(info)
    return get_incentives_today


def make_create_support_ticket():
    async def create_support_ticket(params: FunctionCallParams):
        msisdn = normalize_msisdn(params.arguments["phone_number"])
        summary = params.arguments["summary"]
        cat = params.arguments["category"]
        ticket_id = "OLA-"+str(abs(hash((msisdn, cat, summary)))%10_000_000).zfill(7)
        await params.result_callback({"ticket_id": ticket_id, "status": "created"})
    return create_support_ticket

# Registration helper
def register_ola_tools(llm) -> ToolsSchema:
    tools = ToolsSchema(standard_tools=[
        verify_driver_number_schema,
        get_driver_account_health_schema,
        check_app_online_status_schema,
        get_supply_demand_snapshot_schema,
        fetch_wallet_and_payouts_schema,
        get_incentives_today_schema,
        push_device_reauth_schema,
        # create_support_ticket_schema,
    ])
    llm.register_function("verify_driver_number",      make_verify_driver_number())
    llm.register_function("get_driver_account_health", make_get_driver_account_health())
    llm.register_function("check_app_online_status",   make_check_app_online_status())
    llm.register_function("get_supply_demand_snapshot",make_get_supply_demand_snapshot())
    llm.register_function("fetch_wallet_and_payouts",  make_fetch_wallet_and_payouts())
    llm.register_function("get_incentives_today",      make_get_incentives_today())
    llm.register_function("push_device_reauth",        make_push_device_reauth())
    llm.register_function("create_support_ticket",     make_create_support_ticket())
    return tools
