from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from postgrest.exceptions import APIError
import hashlib


_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid",
}

def canonicalize_url(
    url: str,
    *,
    force_https: bool = True,
    strip_www: bool = True,
    normalize_trailing_slash: bool = True,
) -> str:
    """
    Make URLs stable to avoid duplicates:
    - strips fragments
    - strips common tracking query params
    - sorts remaining query params
    - optionally forces https
    - strips default ports (:80, :443)
    - optionally strips www.
    - optionally normalizes trailing slash for "path-only" pages
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    u = urlparse(raw)

    # If the URL came in without a scheme (e.g. "site.com/page"), try to treat it as https.
    # urlparse("site.com/page") interprets "site.com" as scheme, so fix that case.
    if u.scheme and not u.netloc:
        # likely "example.com/path" parsed as scheme="example.com"
        u = urlparse("https://" + raw)

    scheme = (u.scheme or "https").lower()
    if force_https and scheme == "http":
        scheme = "https"

    host = (u.hostname or "").lower()
    if strip_www and host.startswith("www."):
        host = host[4:]

    # Rebuild netloc with optional non-default port
    port = u.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    if port and not default_port:
        netloc = f"{host}:{port}"
    else:
        netloc = host

    # Filter + sort query params (keep non-tracking, keep blank values)
    query_pairs = [
        (k, v)
        for (k, v) in parse_qsl(u.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query_pairs.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(query_pairs, doseq=True)

    # Normalize path
    path = u.path or "/"
    if normalize_trailing_slash:
        # Treat "/page" and "/page/" as same.
        # Keep "/" as "/".
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

    # Drop fragment always
    fragment = ""

    clean = u._replace(
        scheme=scheme,
        netloc=netloc,
        path=path,
        params="",   # rarely used; safe to drop for canonicalization
        query=query,
        fragment=fragment,
    )
    return urlunparse(clean)


def get_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.replace("www.", "")
    except Exception:
        return ""

def hash_text(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


@dataclass
class CacheDecision:
    url: str
    domain: str
    should_fetch: bool
    reason: str


class TrendSourceCacheStore:
    def __init__(self, storage_service):
        self.supabase = storage_service.supabase

    def filter_urls_to_fetch(
        self,
        urls: List[str],
        *,
        ttl_days: int = 30,
    ) -> List[CacheDecision]:
        """
        Returns a decision per URL: should_fetch True if not fetched within ttl_days.
        """
        now = datetime.now(timezone.utc)
        ttl_cutoff = now - timedelta(days=ttl_days)

        canon = [canonicalize_url(u) for u in urls if u]
        canon = list(dict.fromkeys(canon))  # preserve order, unique

        if not canon:
            return []

        # Supabase "in_" query can take a list
        resp = self.supabase.table("trend_source_cache").select("url,last_fetched_at").in_("url", canon).execute()
        rows = resp.data or []
        last_map = {r["url"]: r.get("last_fetched_at") for r in rows if r.get("url")}

        decisions: List[CacheDecision] = []
        for u in canon:
            dom = get_domain(u)
            last = last_map.get(u)

            if not last:
                decisions.append(CacheDecision(url=u, domain=dom, should_fetch=True, reason="not_seen"))
                continue

            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            except Exception:
                # If parse fails, be safe and refetch
                decisions.append(CacheDecision(url=u, domain=dom, should_fetch=True, reason="bad_timestamp"))
                continue

            if last_dt < ttl_cutoff:
                decisions.append(CacheDecision(url=u, domain=dom, should_fetch=True, reason="expired"))
            else:
                decisions.append(CacheDecision(url=u, domain=dom, should_fetch=False, reason="fresh_cached"))

        return decisions

    def upsert_fetched(
        self,
        *,
        url: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        canon = canonicalize_url(url)
        dom = get_domain(canon)

        # What we want on first insert only (includes first_seen_at)
        insert_row = {
            "url": canon,
            "domain": dom,
            "first_seen_at": now_iso,
            "last_fetched_at": now_iso,
        }
        if title:
            insert_row["title"] = title
        if content:
            insert_row["content_hash"] = hash_text(content)

        # What we want on subsequent updates (DO NOT include first_seen_at)
        update_row = {
            "domain": dom,
            "last_fetched_at": now_iso,
        }
        if title:
            update_row["title"] = title
        if content:
            update_row["content_hash"] = hash_text(content)

        try:
            # Attempt INSERT first. Requires a UNIQUE constraint on "url".
            self.supabase.table("trend_source_cache").insert(insert_row).execute()
            return
        except APIError as e:
            # If it's a conflict/duplicate key, do UPDATE instead.
            # PostgREST commonly uses 409 for conflicts.
            status = getattr(e, "status_code", None)

            is_conflict = status == 409
            # Fallback heuristic if status_code isn't present:
            msg = str(e).lower()
            if not is_conflict and ("duplicate" in msg or "already exists" in msg or "conflict" in msg):
                is_conflict = True

            if not is_conflict:
                raise  # real error, bubble up

        # Update existing row WITHOUT overwriting first_seen_at
        self.supabase.table("trend_source_cache").update(update_row).eq("url", canon).execute()