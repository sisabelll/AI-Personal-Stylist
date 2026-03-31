from datetime import date
from postgrest.exceptions import APIError

class UsageGuard:
    def __init__(self, storage_service, daily_budget_usd: float):
        self.supabase = storage_service.supabase
        self.daily_budget = float(daily_budget_usd)

    def _get_spent_today(self) -> float:
        today = date.today().isoformat()

        try:
            resp = (
                self.supabase
                .table("api_usage_guard")
                .select("usd_spent")
                .eq("date", today)
                .limit(1)
                .execute()
            )
        except APIError as e:
            # postgrest-py sometimes throws on 204 No Content (no rows)
            err = getattr(e, "args", None)
            if err and isinstance(err[0], dict) and str(err[0].get("code")) == "204":
                return 0.0
            # some versions store it differently; fallback to string check
            if "code" in str(e) and "204" in str(e):
                return 0.0
            raise

        rows = getattr(resp, "data", None) or []
        if not rows:
            return 0.0

        val = rows[0].get("usd_spent")
        try:
            return float(val or 0.0)
        except Exception:
            return 0.0

    def can_spend(self, estimated_usd: float) -> bool:
        spent = self._get_spent_today()
        return (spent + float(estimated_usd)) <= self.daily_budget

    def record_spend(self, usd: float) -> None:
        """
        Read+write is fine for a single local script.
        If you run this concurrently, switch to an RPC that increments atomically.
        """
        today = date.today().isoformat()
        new_total = self._get_spent_today() + float(usd)

        # Upsert total. Some clients also throw 204 on upsert; if you see that,
        # add .select("date") after upsert to force a JSON response.
        try:
            self.supabase.table("api_usage_guard").upsert({
                "date": today,
                "usd_spent": new_total,
            }).execute()
        except APIError as e:
            err = getattr(e, "args", None)
            if err and isinstance(err[0], dict) and str(err[0].get("code")) == "204":
                return
            if "code" in str(e) and "204" in str(e):
                return
            raise
