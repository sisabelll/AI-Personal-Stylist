import requests
from urllib.parse import urlparse
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from core.config import Config

# Bump to invalidate Streamlit cache when query logic changes.
CACHE_VERSION = "v2"

BLOCKED_DOMAINS = {
    "wordpress.com",
    "blogspot.com",
    "pinterest.com",
    "pinimg.com",
}

BLOCKED_SUBSTRINGS = (
    "clipart",
    "vector",
    "svg",
    "icon",
    "logo",
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
    return False

# ---------------------------------------------------------
# 1. THE CACHED IMAGE SEARCHER
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, persist="disk")
def cached_google_image_search(query: str, api_key: str, cse_id: str, cache_version: str = CACHE_VERSION) -> dict:
    """
    Fetches the #1 most relevant VISUAL image from Google Images.
    """
    if not api_key or not cse_id: return None

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key, "cx": cse_id, "q": query,
        "searchType": "image", 
        "num": 3,
        "safe": "active", "imgSize": "large", "imgType": "photo"
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        
        if "items" in data:
            # 🟢 LOOP THROUGH CANDIDATES
            for item in data["items"]:
                image_url = item.get("link")
                display_link = item.get("displayLink")
                context_link = item.get("image", {}).get("contextLink")

                # Skip low-quality or spammy sources (clipart/wordpress/etc.)
                if _is_blocked_source(image_url, display_link, context_link):
                    continue
                
                # 🛡️ THE VALIDATION CHECK
                if is_image_accessible(image_url):
                    return {
                        "title": item.get("title"),
                        "image": image_url,
                        "link": context_link,
                        "source": item.get("displayLink"),
                        "price": None 
                    }
                else:
                    print(f"🚫 blocked/broken image: {image_url}")
                    continue # Try the next one
            
    except Exception as e:
        print(f"❌ Search Error: {e}")
        
    return None


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
    """
    if not url: return False
    
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
