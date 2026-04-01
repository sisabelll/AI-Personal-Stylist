import requests
from urllib.parse import urlparse
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from core.config import Config

# Bump to invalidate Streamlit cache when query logic changes.
CACHE_VERSION = "v5"

# Curated fashion domains for restricted search.
# Appended to the query as "OR site:X" clauses — the only multi-domain restriction
# method supported by the Google CSE API (siteSearch only accepts a single domain).
ALLOWED_FASHION_DOMAINS = [
    "net-a-porter.com",
    "ssense.com",
    "farfetch.com",
    "mytheresa.com",
    "matchesfashion.com",
    "shopbop.com",
    "revolve.com",
    "aritzia.com",
    "cos.com",
    "stories.com",
    "zara.com",
    "mango.com",
    "reiss.com",
]

# Site filter string appended to restricted queries
_SITE_FILTER = " OR ".join(f"site:{d}" for d in ALLOWED_FASHION_DOMAINS)

BLOCKED_DOMAINS = {
    "wordpress.com",
    "blogspot.com",
    "pinterest.com",
    "pinimg.com",
    "amazon.com",
    "amazon.co.uk",
    "etsy.com",
    "ebay.com",
    "snapchat.com",
    "instagram.com",
    "tiktok.com",
    "nymag.com",
    "buzzfeed.com",
    "wikimedia.org",
    "wikipedia.org",
}

BLOCKED_SUBSTRINGS = (
    "clipart",
    "vector",
    "svg",
    "icon",
    "logo",
)

# TLDs that never host retail product pages
BLOCKED_TLDS = (".edu", ".gov", ".mil")

# Image CDNs for ALLOWED_FASHION_DOMAINS that block HEAD/GET probes but serve real product images.
# Skip the live accessibility check for these — if Google indexed them, they're real.
TRUSTED_IMAGE_CDNS = (
    "cdn-images.farfetch-contents.com",
    "www.mytheresa.com",
    "media.ssense.com",
    "images.net-a-porter.com",
    "image.reiss.com",
    "media.revolve.com",
    "img.shopbop.com",
    "www.cos.com",
    "www.stories.com",
)

# Path/title keywords that reliably indicate a non-retail page on any domain
BLOCKED_CONTEXT_KEYWORDS = (
    "faculty",
    "staff",
    "professor",
    "department",
    "university",
    "college",
    "nonprofit",
    "foundation",
    "museum",
    "hospital",
    "clinic",
    "welcome-new",
    "welcomes-new",
    "meets-the-team",
    "about-us",
    "our-team",
    "/news/",
    "/press/",
    "/blog/",
    "/events/",
)


def _is_blocked_source(url: Optional[str], display_link: Optional[str], context_link: Optional[str]) -> bool:
    for candidate in (url, context_link):
        if not candidate:
            continue
        host = (urlparse(candidate).netloc or "").lower()
        for dom in BLOCKED_DOMAINS:
            if host == dom or host.endswith(f".{dom}"):
                return True
        lowered = candidate.lower()
        if any(s in lowered for s in BLOCKED_SUBSTRINGS):
            return True
    if display_link:
        host = display_link.lower()
        for dom in BLOCKED_DOMAINS:
            if host == dom or host.endswith(f".{dom}"):
                return True
        if any(s in host for s in BLOCKED_SUBSTRINGS):
            return True

    # Extra checks on context_link only (the page URL, not the image URL)
    if context_link:
        host = (urlparse(context_link).netloc or "").lower()
        if any(host.endswith(tld) for tld in BLOCKED_TLDS):
            return True
        lowered = context_link.lower()
        if any(kw in lowered for kw in BLOCKED_CONTEXT_KEYWORDS):
            return True
        # Block localized/non-US retail pages — mobile sub-paths and non-USD currency params
        if "/mobile/" in lowered:
            return True
        parsed_cl = urlparse(context_link)
        qs = (parsed_cl.query or "").lower()
        if "currency=" in qs and "currency=usd" not in qs:
            return True
        if "lang=" in qs and not any(x in qs for x in ("lang=en", "lang=us")):
            return True

    return False

# ---------------------------------------------------------
# 1. THE CACHED IMAGE SEARCHER
# ---------------------------------------------------------
def _run_google_image_search(query: str, api_key: str, cse_id: str, site_restrict: bool = True) -> Optional[dict]:
    """
    Single Google Custom Search call. When site_restrict=True, appends OR site: clauses
    to the query to restrict results to ALLOWED_FASHION_DOMAINS. This is the correct
    multi-domain restriction method — the siteSearch API param only accepts a single domain.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    q = f"({query}) ({_SITE_FILTER})" if site_restrict else query
    params = {
        "key": api_key, "cx": cse_id, "q": q,
        "searchType": "image",
        "num": 5,
        "safe": "active", "imgSize": "large", "imgType": "photo",
        "hl": "en",   # interface language → English results
        "gl": "us",   # geolocation → US market pricing/URLs
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        print(f"🔍 CSE query ({'restricted' if site_restrict else 'open'}): {query[:80]}")
        if "items" in data:
            for item in data["items"]:
                image_url = item.get("link")
                display_link = item.get("displayLink")
                context_link = item.get("image", {}).get("contextLink")

                if not site_restrict and _is_blocked_source(image_url, display_link, context_link):
                    continue

                if is_image_accessible(image_url):
                    print(f"✅ Image found: {display_link}")
                    return {
                        "title": item.get("title"),
                        "image": image_url,
                        "link": context_link,
                        "source": display_link,
                        "price": None,
                    }
                else:
                    print(f"🚫 blocked/broken image: {image_url}")
        else:
            print(f"⚠️  No items in CSE response. Error: {data.get('error', {}).get('message', '')}")
    except Exception as e:
        print(f"❌ Search Error: {e}")

    return None


@st.cache_data(show_spinner=False, persist="disk")
def cached_google_image_search(query: str, api_key: str, cse_id: str, cache_version: str = CACHE_VERSION) -> dict:
    """
    Fetches the best available fashion image for a query.
    Strategy:
      1. Restricted search across ALLOWED_FASHION_DOMAINS (guaranteed editorial quality).
      2. If no result, retry with a simplified query (first 4 words) on restricted domains.
      3. If still no result, fall back to open web search with block-list filtering.
    """
    if not api_key or not cse_id:
        return None

    # Pass 1: restricted to curated fashion domains
    result = _run_google_image_search(query, api_key, cse_id, site_restrict=True)
    if result:
        return result

    # Pass 2: simplified query, still restricted (long queries with negatives can return 0 results)
    simple_query = " ".join(query.split()[:5])
    if simple_query != query:
        print(f"🔄 Retrying with simplified query: {simple_query}")
        result = _run_google_image_search(simple_query, api_key, cse_id, site_restrict=True)
        if result:
            return result

    # Pass 3: open web search with block-list as last resort
    print(f"🌐 Falling back to open web search for: {simple_query}")
    return _run_google_image_search(simple_query, api_key, cse_id, site_restrict=False)


# ---------------------------------------------------------
# 2. THE CATALOG CLIENT
# ---------------------------------------------------------
class CatalogClient:
    """
    Fetches aesthetic imagery using Google Custom Search.
    Prioritizes 'Vibe' over 'Product Metadata'.
    """

    def __init__(self):
        self.api_key = Config.GOOGLE_API_KEY
        self.cse_id = Config.GOOGLE_CSE_ID
        
        if not self.api_key or not self.cse_id:
            print("⚠️ CatalogClient: Missing GOOGLE_API_KEY or GOOGLE_CSE_ID.")

        # st.cache_data.clear() 
        # print("🧹 Cache cleared!")

    def find_item_image(self, precise_query: str) -> dict:
        """Single item search."""
        return cached_google_image_search(precise_query, self.api_key, self.cse_id)

    def search_products_parallel(self, items: list) -> dict:
        print(f"\n📢 CATALOG RECEIVED INPUT TYPE: {type(items)}")
        print(f"📢 RAW INPUT DATA: {str(items)[:100]}...\n")
        if isinstance(items, dict) or not isinstance(items, list):
            print("🚨 CRITICAL ERROR: Invalid input type.")
            return {}
        
        valid_items = [i for i in items if not isinstance(i, str)]
        items = valid_items
        
        results = {}
        items_to_search = []
        
        for item in items:
            item_name = item.get('item_name', 'Unknown')
            items_to_search.append(item)
            results[item_name] = None

        if not items_to_search: return results

        print(f"🛍️ Correctly searching for {len(items_to_search)} items...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_item = {}
            for item in items_to_search:
                # Use 'search_query' if available, otherwise 'item_name'
                query_str = item.get('search_query', item.get('item_name'))
                
                # Verify we are passing a string
                if not isinstance(query_str, str): 
                    query_str = str(query_str)

                # Submit the STRING, not the DICT
                future = executor.submit(self.find_item_image, query_str)
                future_to_item[future] = item
            
            for future in as_completed(future_to_item):
                item = future_to_item[future]
                item_name = item.get('item_name')
                try:
                    product = future.result()
                    # Only overwrite if we found a valid product
                    if product:
                        results[item_name] = product
                    else:
                        # If search fails, keep item but WIPE the old image to be safe
                        item['image'] = None
                        results[item_name] = item
                except Exception as e:
                    print(f"❌ Error: {e}")
                    results[item_name] = item

        return results
    
def is_image_accessible(url: str) -> bool:
    """
    Checks if an image URL is alive and accessible without downloading the whole file.
    Trusted fashion CDNs are whitelisted and bypass the live check — they block probes
    but always serve real product images when Google has indexed them.
    """
    if not url: return False
    host = (urlparse(url).netloc or "").lower()
    if any(host == cdn or host.endswith(f".{cdn}") for cdn in TRUSTED_IMAGE_CDNS):
        return True
    
    try:
        # We use stream=True and a tight timeout (1s) to be fast.
        # We pretend to be a browser (User-Agent) to bypass basic anti-bot blocks.
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
        }
        
        # HEAD request only fetches headers (metadata), not the image body. Super fast.
        response = requests.head(url, headers=headers, timeout=1.5, allow_redirects=True)
        if response.status_code == 200 and 'image' in response.headers.get('Content-Type', ''):
            return True

        # Some hosts block HEAD but allow GET; try a tiny streamed GET as fallback.
        response = requests.get(url, headers=headers, timeout=2.5, stream=True, allow_redirects=True)
        if response.status_code == 200 and 'image' in response.headers.get('Content-Type', ''):
            return True
            
    except:
        # If it times out or fails, assume it's broken.
        return False
        
    return False
