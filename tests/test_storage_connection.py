"""
Regression tests for the scheduled Inspiration Agent failures.

Every failed run between 2026-07-27 and 2026-08-24 ended the same way:

    httpcore.ConnectError: [Errno -2] Name or service not known

40 lines of httpx/httpcore frames that never mention Supabase, and that look
identical whether the project is paused or the runner had one bad second of
DNS. check_connection separates those two cases and says which one happened.
"""
import httpx
import pytest

from services.storage import StorageService


class FakeExecutor:
    def __init__(self, table):
        self._table = table

    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        self._table.calls += 1
        err = self._table.errors.pop(0) if self._table.errors else None
        if err:
            raise err
        return type("Resp", (), {"data": []})()


class FakeClient:
    def __init__(self, errors=None):
        self.errors = list(errors or [])
        self.calls = 0

    def table(self, name):
        return FakeExecutor(self)


def make_storage(errors=None):
    storage = StorageService.__new__(StorageService)   # skip env validation
    storage.supabase = FakeClient(errors)
    storage.db_admin = storage.supabase
    return storage


def dns_error():
    """The exact shape the runner produced, cause chain included."""
    inner = OSError(-2, "Name or service not known")
    err = httpx.ConnectError("[Errno -2] Name or service not known")
    err.__cause__ = inner
    return err


class TestChecksConnection:
    def test_passes_when_supabase_answers(self):
        storage = make_storage()
        storage.check_connection(attempts=3, delay=0)
        assert storage.supabase.calls == 1, "should not retry a healthy connection"

    def test_retries_then_succeeds_on_a_transient_blip(self):
        storage = make_storage(errors=[dns_error(), dns_error()])
        storage.check_connection(attempts=5, delay=0)
        assert storage.supabase.calls == 3

    def test_persistent_dns_failure_names_the_paused_project(self):
        storage = make_storage(errors=[dns_error()] * 5)
        with pytest.raises(ConnectionError) as exc:
            storage.check_connection(attempts=5, delay=0)

        msg = str(exc.value)
        assert "does not resolve" in msg
        assert "paused" in msg, "must say what actually happened"
        assert "dashboard" in msg, "must say what to do about it"
        assert storage.supabase.calls == 5

    def test_non_dns_failure_is_reported_as_itself(self):
        storage = make_storage(errors=[RuntimeError("permission denied")] * 3)
        with pytest.raises(ConnectionError) as exc:
            storage.check_connection(attempts=3, delay=0)

        msg = str(exc.value)
        assert "permission denied" in msg
        assert "paused" not in msg, "don't blame pausing for an unrelated error"

    def test_gives_up_after_the_attempt_budget(self):
        storage = make_storage(errors=[dns_error()] * 20)
        with pytest.raises(ConnectionError):
            storage.check_connection(attempts=4, delay=0)
        assert storage.supabase.calls == 4


class TestDnsDetection:
    @pytest.mark.parametrize("text", [
        "[Errno -2] Name or service not known",          # linux runner
        "nodename nor servname provided, or not known",  # macOS
        "Temporary failure in name resolution",
        "getaddrinfo failed",
        "net::ERR_NAME_NOT_RESOLVED",
    ])
    def test_recognises_each_platforms_wording(self, text):
        assert StorageService._looks_like_dns_failure(Exception(text))

    def test_walks_the_cause_chain(self):
        assert StorageService._looks_like_dns_failure(dns_error())

    def test_ignores_unrelated_errors(self):
        assert not StorageService._looks_like_dns_failure(ValueError("bad row"))
        assert not StorageService._looks_like_dns_failure(None)

    def test_survives_a_cyclic_cause_chain(self):
        a, b = Exception("a"), Exception("b")
        a.__cause__ = b
        b.__cause__ = a
        assert StorageService._looks_like_dns_failure(a) is False
