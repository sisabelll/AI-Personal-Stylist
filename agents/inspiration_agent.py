from __future__ import annotations
from typing import Dict, List, Any
from urllib.parse import urlencode
import requests

from services.storage import StorageService
from services.inspiration_store import InspirationStore
from services.client import OpenAIClient
from services.usage_guard import UsageGuard
from services.instagram_client import ApifyInstagramClient
from core.config import Config, get_logger
from core.schemas import InspirationExpandLLM

logger = get_logger(__name__)

# ========================
# SAFEGUARDS
# ========================
DAILY_BUDGET_USD = 0.30     # ~$9/month across all users
MAX_IMAGES_PER_QUERY = 5
MAX_QUERIES_PER_RUN = 20    # caps Google CSE API calls per user run (full run)
MAX_MINI_QUERIES = 4        # Google CSE calls for a mini-expansion
MINI_IMAGES_PER_QUERY = 8   # more images per query for mini-expansion

# Allowlist: only accept images whose page_url comes from these fashion domains.
# This is the primary quality gate — far more reliable than a blocklist.
_FASHION_DOMAINS = {
    # Editorial
    "vogue.com", "harpersbazaar.com", "elle.com", "whowhatwear.com",
    "instyle.com", "glamour.com", "refinery29.com", "marieclaire.com",
    "wmagazine.com", "nylon.com", "byrdie.com",
    # Street style / blogs
    "thesartorialist.com", "stockholmstreetstyle.com", "advancedstyle.blogspot.com",
    "gastrochic.com", "songofstyle.com", "aclotheshorse.com",
    # Retail editorial (lookbooks, campaigns)
    "net-a-porter.com", "mytheresa.com", "ssense.com", "matchesfashion.com",
    "farfetch.com", "24sevres.com", "luisaviaroma.com",
    # Brand own sites (direct lookbooks)
    "therow.com", "khaite.com", "toteme.com", "celine.com", "loewe.com",
    "bottegaveneta.com", "jilsander.com", "acnestudios.com", "cos.com", "arket.com",
    # Street/celebrity style aggregators
    "who-what-wear.com", "popsugar.com", "justjared.com", "usmagazine.com",
}


class GoogleCSEImageClient:
    """Google Custom Search — image mode."""

    def __init__(self):
        self.api_key = Config.GOOGLE_API_KEY
        self.cse_id = Config.GOOGLE_CSE_ID
        if not self.api_key or not self.cse_id:
            raise RuntimeError("Missing GOOGLE_API_KEY or GOOGLE_CSE_ID")

    def image_search(self, q: str, num: int = 5) -> List[Dict[str, Any]]:
        params = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": q,
            "num": min(num, 10),
            "searchType": "image",
            "imgSize": "large",
            "imgType": "photo",
            "safe": "off",
        }
        url = "https://www.googleapis.com/customsearch/v1?" + urlencode(params)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        results = []
        for it in items:
            img = it.get("image") or {}
            image_url = it.get("link") or ""
            if not image_url:
                continue
            # Only keep images whose page context is a known fashion domain
            page_url = img.get("contextLink") or ""
            page_domain = _domain_of(page_url)
            if not any(page_domain == d or page_domain.endswith("." + d) for d in _FASHION_DOMAINS):
                continue
            results.append({
                "image_url": image_url,
                "page_url": img.get("contextLink") or "",
                "title": it.get("title") or "",
            })
        return results


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _filter_fashion_posts(
    items: List[Dict[str, Any]],
    client: OpenAIClient,
) -> List[Dict[str, Any]]:
    """
    Use GPT-4o-mini to classify each post as outfit/fashion-relevant or not.
    Sends all captions in one batched call to keep cost minimal.
    Posts with no caption get the benefit of the doubt (kept).
    """
    if not items:
        return items

    # Posts with no caption — keep them (can't classify, usually fine from fashion accounts)
    captioned = [(i, it) for i, it in enumerate(items) if (it.get("caption") or "").strip()]
    no_caption_indices = {i for i, it in enumerate(items) if not (it.get("caption") or "").strip()}

    if not captioned:
        return items

    numbered = "\n".join(
        f"{idx}. {it['caption'][:200]}" for idx, (i, it) in enumerate(captioned)
    )

    system = (
        "You are a fashion content classifier. "
        "Given a numbered list of Instagram post captions, reply with ONLY a JSON array "
        "of the indices (0-based) of posts that show or describe an actual outfit, "
        "clothing item, or personal style — i.e. content that belongs on a fashion inspiration board. "
        "Exclude: ads/promotions, motivational quotes, food, travel, pets, brand giveaways, "
        "fitness content, and any post not about what someone is wearing. "
        "Example reply: [0, 2, 4]"
    )

    try:
        raw = client.call_api(
            model=Config.OPENAI_MODEL_FAST,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Captions:\n{numbered}"},
            ],
            temperature=0,
            max_tokens=256,
        )
        import json as _json
        import re as _re
        match = _re.search(r'\[[\d,\s]*\]', raw or "")
        keep_indices = set(_json.loads(match.group())) if match else set(range(len(captioned)))
    except Exception as e:
        logger.warning("[InspirationAgent] Fashion filter failed, keeping all: %s", e)
        return items

    kept = []
    for i, it in enumerate(items):
        if i in no_caption_indices:
            kept.append(it)
        else:
            captioned_idx = next(ci for ci, (orig_i, _) in enumerate(captioned) if orig_i == i)
            if captioned_idx in keep_indices:
                kept.append(it)
    return kept


class InspirationAgent:
    def __init__(self, client):
        self.client = client

    def expand(
        self,
        user_profile,
        promoted: List[str] | None = None,
        demoted: List[str] | None = None,
    ) -> Dict[str, Any]:
        prefs = user_profile.get("preferences") or {}
        icons = prefs.get("style_icons") or []
        brands = prefs.get("favorite_brands") or []
        wear = (user_profile.get("wear_preference") or "unisex").lower()
        promoted = promoted or []
        demoted  = demoted  or []

        system = (
            "You are a fashion research assistant.\n"
            "Given initial style icons and brands, expand into:\n"
            "- similar_icons: 6-10 names\n"
            "- motifs: 6-10 short, SEARCHABLE phrases (items/silhouettes/materials/styling moves)\n"
            "- brand_angles: 4-8 (how to search brands)\n\n"

            "OUTPUT CONTRACT (STRICT):\n"
            "Return STRICT JSON ONLY with exactly these keys: similar_icons, motifs, brand_angles.\n"
            "No extra keys. No markdown. No commentary.\n\n"

            "RULES — SIMILAR_ICONS:\n"
            "- Prefer people known for STREET STYLE / OFF-DUTY looks.\n"
            "- At least 4 must be strongly aligned with the seed lane (Bella/Sofia + The Row/Khaite/Toteme vibe).\n"
            "- Avoid random red-carpet-only picks.\n"
            "- For instagram_handle: provide the exact public Instagram username (no @). "
            "  Leave null only if you are not confident it is correct.\n\n"

            "RULES — MOTIFS (MOST IMPORTANT):\n"
            "- Motifs must be CONCRETE and SEARCHABLE: include at least one GARMENT/ITEM noun "
            "(e.g., blazer, trench, loafer, slingback, skirt, denim, knit, tote).\n"
            "- Avoid vague vibe-only phrases like 'Parisian chic', 'minimal vibes', 'effortlessly chic'.\n"
            "- At least 3 motifs must be STYLING MOVES (not just basics). Examples:\n"
            "  'sheer black socks with loafers', 'tonal oatmeal layering (knit + wool + leather)', "
            "'longline blazer with short hem balance', 'espresso leather outerwear over ivory base'.\n"
            "- Includes must be 2-4 CONCRETE tokens; excludes must be 1-4 CONCRETE searchable negatives "
            "(e.g., 'logo', 'neon', 'chunky', 'distressed', 'boho'), not abstract adjectives.\n\n"

            "RULES — BRAND_ANGLES:\n"
            "- brand must be one of the seed brands.\n"
            "- angle should be one of: lookbook, campaign, runway, street_style, editorial, best_sellers.\n"
            "- query_hint MUST NOT repeat the brand name. It should be only the suffix/angle words.\n"
            "  Good query_hint examples: 'lookbook', 'campaign images', 'runway collection', 'street style', 'editorial feature'.\n"
            "  Bad query_hint examples: 'The Row lookbook styles', 'Khaite editorial features'.\n"
            "- For instagram_handle: provide the brand's exact public Instagram username (no @). "
            "  Leave null only if you are not confident it is correct.\n\n"

            "QUALITY BAR:\n"
            "- Keep everything modern and specific.\n"
            "- No filler items.\n"
        )

        user: Dict[str, Any] = {
            "wear_preference": wear,
            "seed_icons": icons,
            "seed_brands": brands,
        }
        if promoted:
            user["user_has_responded_well_to"] = promoted[:10]
            system += (
                "\nTASTE SIGNALS (from user's board interactions):\n"
                "- user_has_responded_well_to: icons/brands the user has liked. "
                "Bias similar_icons toward this aesthetic lane — find more like these.\n"
            )
        if demoted:
            user["user_has_dismissed"] = demoted[:10]
            system += (
                "- user_has_dismissed: icons/brands the user has hidden. "
                "Avoid recommending figures or brands in the same aesthetic lane.\n"
            )

        parsed: InspirationExpandLLM = self.client.structured(
            model=Config.OPENAI_MODEL_FAST,
            system=system,
            user=user,
            response_model=InspirationExpandLLM,
            temperature=0.2,
            max_tokens=1200,
        )

        data = parsed.model_dump()

        # Post-validators that depend on runtime seeds (LLM can't see your python validators)
        seed_brand_set = {b.strip().lower() for b in brands}
        data["brand_angles"] = [
            ba for ba in data["brand_angles"]
            if ba["brand"].strip().lower() in seed_brand_set
        ]

        # Defensive: if the model violated brand rule and filtering empties it, rebuild deterministic angles
        if not data["brand_angles"] and brands:
            data["brand_angles"] = [
                {"brand": b, "angle": "lookbook", "query_hint": "lookbook campaign runway", "priority": 2}
                for b in brands[:6]
            ]

        return {
            "seed_icons": icons,
            "seed_brands": brands,
            **data,
        }

    def build_brand_query(self, brand: str, hint: str) -> str:
        """Defensive helper to avoid duplicated brand tokens."""
        brand_l = brand.lower()
        hint = (hint or "").strip()

        hint_clean = " ".join(
            w for w in hint.split()
            if w.lower() not in brand_l.split()
        )

        return f"{brand} {hint_clean} outfit".strip()

    def build_image_queries(self, expanded: Dict[str, Any]) -> List[Dict[str, str]]:
        queries = []

        icon_names = (expanded.get("seed_icons") or [])[:3] + [i["name"] for i in (expanded.get("similar_icons") or [])[:8]]
        for icon in icon_names:
            if not icon:
                continue
            queries.append({
                "source_type": "icon",
                "source_name": icon,
                "q": f'{icon} fashion style outfit street style -site:edu -site:gov -site:linkedin.com -site:wikipedia.org'
            })

        for ba in (expanded.get("brand_angles") or [])[:8]:
            brand = ba.get("brand")
            hint = ba.get("query_hint") or ba.get("angle") or "lookbook"
            queries.append({
                "source_type": "brand",
                "source_name": brand,
                "q": self.build_brand_query(brand, hint) + " fashion editorial",
            })

        for m in (expanded.get("motifs") or [])[:10]:
            phrase = m["phrase"]
            inc = " ".join(m.get("includes") or [])
            exc = " ".join([f"-{t}" for t in (m.get("excludes") or [])])
            queries.append({
                "source_type": "motif",
                "source_name": phrase,
                "q": f'{phrase} {inc} street style fashion outfit 2024 2025 2026 {exc}'.strip()
            })

        return queries

    def fetch_images(
        self,
        queries: List[Dict[str, str]],
        google: GoogleCSEImageClient,
        num_per_query: int = MAX_IMAGES_PER_QUERY,
    ) -> List[Dict[str, Any]]:
        """Fetch image results for each query via Google CSE image search."""
        items = []
        for q_info in queries[:MAX_QUERIES_PER_RUN]:
            try:
                results = google.image_search(q_info["q"], num=num_per_query)
                for r in results:
                    if not r.get("image_url"):
                        continue
                    page_url = r.get("page_url") or ""
                    page_domain = _domain_of(page_url)
                    if not any(page_domain == d or page_domain.endswith("." + d) for d in _FASHION_DOMAINS):
                        continue
                    items.append({
                        "source_type": q_info["source_type"],
                        "source_name": q_info["source_name"],
                        "image_url": r["image_url"],
                        "page_url": page_url,
                        "caption": r.get("title") or "",
                        "tags": [],
                        "score": 0.5,
                    })
                logger.debug("Fetched %d images for: %s", len(results), q_info["q"][:60])
            except Exception as e:
                logger.warning("Image search failed for '%s': %s", q_info["q"][:60], e)
        return items


def run(user_id: str, user_profile: dict) -> None:
    """
    Full inspiration pipeline for one user:
      1. Read feedback signals from the board (likes/hides)
      2. Decide whether to re-expand the KG (monthly or when feedback threshold hit)
         or reuse the existing one and just refresh images
      3. Fetch fresh web images + Instagram posts
      4. Upsert everything to Supabase

    Called by the GitHub Actions cron workflow and can be triggered manually.
    """
    from datetime import datetime, timezone, timedelta

    storage = StorageService()
    usage = UsageGuard(storage, daily_budget_usd=DAILY_BUDGET_USD)
    inspiration_store = InspirationStore(storage)
    google = GoogleCSEImageClient()
    llm = OpenAIClient()
    agent = InspirationAgent(llm)

    ESTIMATED_LLM_COST = 0.02

    prefs = user_profile.get("preferences") or {}
    icons = prefs.get("style_icons") or []
    brands = prefs.get("favorite_brands") or []
    if not icons and not brands:
        print(f"⚠️  User {user_id}: no seed icons or brands — skipping.")
        return

    # -------- STAGE 1: Read feedback signals --------
    signals = inspiration_store.fetch_feedback_signals(user_id)
    promoted = signals.get("promoted") or []
    demoted  = signals.get("demoted")  or []
    if promoted or demoted:
        print(f"📊 Feedback signals — promoted: {promoted}, demoted: {demoted}")

    # -------- STAGE 2: Decide whether to re-expand KG --------
    existing_kg = inspiration_store.fetch_knowledge_graph(user_id)
    now = datetime.now(timezone.utc)

    last_expanded_str = existing_kg.get("updated_at")
    days_since_expand = 999
    if last_expanded_str:
        try:
            last_expanded = datetime.fromisoformat(last_expanded_str.replace("Z", "+00:00"))
            days_since_expand = (now - last_expanded).days
        except Exception:
            pass

    feedback_count = len(promoted) + len(demoted)
    should_reexpand = (
        not existing_kg                  # first run
        or days_since_expand >= 30       # monthly refresh
        or feedback_count >= 5           # enough taste signal to steer
    )

    if should_reexpand:
        if not usage.can_spend(ESTIMATED_LLM_COST):
            print("⚠️  Budget guard: skipping KG re-expansion, reusing existing.")
            expanded = existing_kg
        else:
            reason = "first run" if not existing_kg else (
                f"{days_since_expand}d since last expand" if days_since_expand >= 30
                else f"{feedback_count} feedback signals"
            )
            print(f"\n🧠 Re-expanding knowledge graph for user {user_id} ({reason})…")
            expanded = agent.expand(user_profile, promoted=promoted, demoted=demoted)
            # Carry promoted/demoted into the stored KG so we can surface them later
            expanded["promoted_icons"]  = [p for p in promoted if p not in brands]
            expanded["promoted_brands"] = [p for p in promoted if p in brands]
            expanded["demoted_sources"] = demoted
            usage.record_spend(ESTIMATED_LLM_COST)
            similar_count = len(expanded.get("similar_icons") or [])
            motif_count   = len(expanded.get("motifs") or [])
            print(f"✅ Knowledge graph: {similar_count} similar icons, {motif_count} motifs")
            inspiration_store.upsert_knowledge_graph(user_id, expanded)
            print("✅ Knowledge graph saved to Supabase")
    else:
        print(f"♻️  Reusing existing KG ({days_since_expand}d old, {feedback_count} feedback signals) — refreshing images only.")
        expanded = existing_kg

    # -------- STAGE 3: Fetch outfit images --------
    queries = agent.build_image_queries(expanded)
    print(f"📸 Fetching images for {len(queries)} queries (cap={MAX_QUERIES_PER_RUN})…")
    items = agent.fetch_images(queries, google, num_per_query=MAX_IMAGES_PER_QUERY)
    print(f"✅ Retrieved {len(items)} images")

    if not items:
        print("⚠️  No images returned — check Google CSE API quota/config.")
        return

    # -------- STAGE 4: Upsert inspiration items (web) --------
    inspiration_store.upsert_items(user_id, items)
    print(f"✅ Upserted {len(items)} web inspiration items for user {user_id}")

    # -------- STAGE 5: Instagram posts via Apify --------
    try:
        apify = ApifyInstagramClient()

        # Collect handles from seed icons, similar icons, and brands
        seed_handles: List[str] = []

        # Seed icons — approximate handle from name (LLM didn't output these directly)
        for icon in expanded.get("seed_icons") or []:
            seed_handles.append(icon.lower().replace(" ", ""))

        # Similar icons — LLM-provided handles (most reliable)
        for icon in expanded.get("similar_icons") or []:
            handle = icon.get("instagram_handle") if isinstance(icon, dict) else getattr(icon, "instagram_handle", None)
            if handle:
                seed_handles.append(handle)

        # Brands — LLM-provided handles
        brand_handles: List[str] = []
        seen_brands: set = set()
        for ba in expanded.get("brand_angles") or []:
            handle = ba.get("instagram_handle") if isinstance(ba, dict) else getattr(ba, "instagram_handle", None)
            brand = ba.get("brand") if isinstance(ba, dict) else getattr(ba, "brand", None)
            if handle and brand and brand not in seen_brands:
                brand_handles.append(handle)
                seen_brands.add(brand)

        all_handles = list(dict.fromkeys(seed_handles + brand_handles))  # dedup, preserve order
        all_handles = all_handles[:12]  # cap to control Apify cost

        if not all_handles:
            print("ℹ️  No Instagram handles found — skipping Stage 5.")
        else:
            print(f"📸 Fetching Instagram posts for {len(all_handles)} handle(s): {all_handles}…")
            # Purge stale Instagram items before inserting fresh ones
            inspiration_store.delete_instagram_items(user_id)
            posts_by_handle = apify.fetch_profiles_batch(all_handles, max_posts_each=15)

            ig_items: List[Dict[str, Any]] = []
            for handle, posts in posts_by_handle.items():
                # Determine source_type: brand handle or icon handle?
                source_type = "brand" if handle in [h.lower() for h in brand_handles] else "icon"
                # Reverse-map handle → display name
                source_name = handle
                for ba in (expanded.get("brand_angles") or []):
                    bh = ba.get("instagram_handle") if isinstance(ba, dict) else getattr(ba, "instagram_handle", None)
                    if bh and bh.lower() == handle:
                        source_name = ba.get("brand") if isinstance(ba, dict) else getattr(ba, "brand", handle)
                        break
                for icon in (expanded.get("similar_icons") or []):
                    ih = icon.get("instagram_handle") if isinstance(icon, dict) else getattr(icon, "instagram_handle", None)
                    if ih and ih.lower() == handle:
                        source_name = icon.get("name") if isinstance(icon, dict) else getattr(icon, "name", handle)
                        break

                for post in posts:
                    ig_items.append({
                        "source_type": source_type,
                        "source_name": source_name,
                        "image_url": post["image_url"],
                        "page_url": post.get("page_url") or "",
                        "caption": post.get("caption") or "",
                        "tags": ["instagram"],
                        "score": 0.7,  # bias Instagram posts slightly higher than web results
                    })

            print(f"✅ Retrieved {len(ig_items)} Instagram posts")
            ig_items = _filter_fashion_posts(ig_items, client)
            print(f"✅ {len(ig_items)} posts passed fashion relevance filter")
            if ig_items:
                inspiration_store.upsert_items(user_id, ig_items)
                print(f"✅ Upserted {len(ig_items)} Instagram items for user {user_id}\n")

    except RuntimeError:
        print("ℹ️  APIFY_API_KEY not set — skipping Instagram stage.")
    except Exception as e:
        print(f"⚠️  Instagram fetch failed (non-fatal): {e}\n")


def mini_expand(
    user_id: str,
    source_name: str,
    source_type: str,
    tags: List[str],
    storage,
    inspiration_store,
) -> int:
    """
    Triggered when a user saves 3+ posts from the same source.
    Fetches ~30 fresh images for that specific source lane and injects
    them into the pool — no LLM call, just targeted Google CSE queries.
    Returns number of new items upserted.
    """
    try:
        google = GoogleCSEImageClient()
    except RuntimeError:
        return 0

    queries: List[Dict[str, str]] = []

    if source_type in ("icon", "instagram"):
        queries.append({
            "source_type": "icon",
            "source_name": source_name,
            "q": f"{source_name} fashion style outfit street style -site:edu -site:gov",
        })
        queries.append({
            "source_type": "icon",
            "source_name": source_name,
            "q": f"{source_name} outfit 2025 2026",
        })
    elif source_type == "brand":
        queries.append({
            "source_type": "brand",
            "source_name": source_name,
            "q": f"{source_name} lookbook campaign fashion editorial",
        })
        queries.append({
            "source_type": "brand",
            "source_name": source_name,
            "q": f"{source_name} runway street style outfit",
        })
    else:
        # motif — use the source_name as the search phrase
        queries.append({
            "source_type": "motif",
            "source_name": source_name,
            "q": f"{source_name} street style fashion outfit 2025 2026",
        })

    # Add a tag-based query for extra variety
    if tags:
        tag_q = " ".join(tags[:3])
        queries.append({
            "source_type": source_type,
            "source_name": source_name,
            "q": f"{tag_q} fashion outfit street style",
        })

    items: List[Dict[str, Any]] = []
    for q_info in queries[:MAX_MINI_QUERIES]:
        try:
            results = google.image_search(q_info["q"], num=MINI_IMAGES_PER_QUERY)
            for r in results:
                if not r.get("image_url"):
                    continue
                page_domain = _domain_of(r.get("page_url") or "")
                if not any(page_domain == d or page_domain.endswith("." + d) for d in _FASHION_DOMAINS):
                    continue
                items.append({
                    "source_type": q_info["source_type"],
                    "source_name": q_info["source_name"],
                    "image_url": r["image_url"],
                    "page_url": r.get("page_url") or "",
                    "caption": r.get("title") or "",
                    "tags": tags or [],
                    "score": 0.65,  # slightly above neutral — user showed interest
                })
        except Exception as e:
            logger.warning("[mini_expand] query failed: %s", e)

    if items:
        inspiration_store.upsert_items(user_id, items)

    logger.info("[mini_expand] +%d items for user %s source '%s'", len(items), user_id, source_name)
    return len(items)


def _load_profile(storage, user_id: str) -> dict:
    profile_resp = (
        storage.supabase.table("profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    profile = profile_resp.data or {}
    prefs_resp = (
        storage.supabase.table("style_preferences")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    profile["preferences"] = prefs_resp.data or {}
    return profile


def _get_due_user_ids(storage) -> List[str]:
    """
    Return user IDs whose inspiration refresh is due based on
    refresh_interval_days and last_refreshed_at in inspiration_knowledge.
    Falls back to all profile IDs for users who have no KG row yet.
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)

    # Users with an existing KG row
    kg_rows = storage.supabase.table("inspiration_knowledge") \
        .select("user_id, last_refreshed_at, refresh_interval_days") \
        .execute().data or []

    due: List[str] = []
    has_kg = set()
    for r in kg_rows:
        uid = r.get("user_id")
        if not uid:
            continue
        has_kg.add(uid)
        last = r.get("last_refreshed_at")
        interval = r.get("refresh_interval_days") or 7
        if not last:
            due.append(uid)
        else:
            try:
                last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if (now - last_dt) >= timedelta(days=interval):
                    due.append(uid)
            except Exception:
                due.append(uid)

    # Users with no KG row at all — always due
    all_profiles = storage.supabase.table("profiles").select("id").execute().data or []
    for p in all_profiles:
        uid = p.get("id")
        if uid and uid not in has_kg:
            due.append(uid)

    return due


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", default=None, help="Run for a single user ID (used by matrix jobs)")
    parser.add_argument("--list-due", action="store_true", help="Print due user IDs as JSON and exit (used by scheduler job)")
    args = parser.parse_args()

    from dotenv import load_dotenv; load_dotenv()
    storage = StorageService()

    if args.list_due:
        import json, os
        due = _get_due_user_ids(storage)
        print(f"Users due for refresh: {due}")
        # Write to GITHUB_OUTPUT if running in Actions
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a") as f:
                f.write(f"user_ids={json.dumps(due)}\n")
    elif args.user_id:
        profile = _load_profile(storage, args.user_id)
        if not profile:
            print(f"❌ Profile not found for user {args.user_id}")
        else:
            run(user_id=args.user_id, user_profile=profile)
    else:
        # No args — run all due users sequentially (local dev / simple deploys)
        due = _get_due_user_ids(storage)
        if not due:
            print("No users due for refresh — nothing to do.")
        else:
            print(f"Running inspiration pipeline for {len(due)} user(s)…")
            for user_id in due:
                profile = _load_profile(storage, user_id)
                try:
                    run(user_id=user_id, user_profile=profile)
                except Exception as e:
                    print(f"❌ Failed for user {user_id}: {e}")
