from dataclasses import dataclass

from app.core.config import get_settings
from app.models import Plan


@dataclass(frozen=True)
class PlanInfo:
    id: Plan
    name: str
    amount_cents: int
    currency: str
    interval: str
    features: tuple[str, ...]

    @property
    def stripe_price_id(self) -> str | None:
        settings = get_settings()
        return {Plan.premium_monthly: settings.stripe_price_premium_monthly,
                Plan.premium_yearly: settings.stripe_price_premium_yearly}[self.id]


PREMIUM_FEATURES = (
    "Premium-only releases",
    "Unlimited playlists",
    "Host group listening sessions",
    "Create collaborative playlists",
)


def get_plans() -> dict[Plan, PlanInfo]:
    settings = get_settings()
    if settings.billing_provider == "razorpay":
        return {
            Plan.premium_monthly: PlanInfo(Plan.premium_monthly, "Premium Monthly", 19900, "inr", "month", PREMIUM_FEATURES),
            Plan.premium_yearly: PlanInfo(Plan.premium_yearly, "Premium Yearly", 119900, "inr", "year", PREMIUM_FEATURES),
        }
    return {
        Plan.premium_monthly: PlanInfo(Plan.premium_monthly, "Premium Monthly", 999, "usd", "month", PREMIUM_FEATURES),
        Plan.premium_yearly: PlanInfo(Plan.premium_yearly, "Premium Yearly", 9999, "usd", "year", PREMIUM_FEATURES),
    }


def get_plan(plan: Plan) -> PlanInfo:
    return get_plans()[plan]


class _PlansProxy(dict):
    def __getitem__(self, key):
        return get_plans()[key]

    def values(self):
        return get_plans().values()

    def items(self):
        return get_plans().items()


PLANS = _PlansProxy()


def plan_for_price(price_id: str | None) -> Plan | None:
    for plan in get_plans().values():
        if price_id and plan.stripe_price_id == price_id:
            return plan.id
    return None
