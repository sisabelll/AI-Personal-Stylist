import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from core.config import Config

# ---------------------------------------------------------
# 1. THE CACHED IMAGE SEARCHER
# ---------------------------------------------------------
@st.cache_data(show_spinner=False, persist="disk")
def cached_google_image_search(query: str, api_key: str, cse_id: str) -> dict:
    """
    Fetches the #1 most relevant VISUAL image from Google Images.
    """
    if not api_key or not cse_id: return None

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key, "cx": cse_id, "q": query,
        "searchType": "image", "num": 1, "safe": "active",
        "imgSize": "large", "imgType": "photo"
    }

    try:
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if "items" in data and len(data["items"]) > 0:
            item = data["items"][0]
            return {
                "title": item.get("title"),
                "image": item.get("link"),
                "link": item.get("image", {}).get("contextLink"),
                "source": item.get("displayLink"),
                "price": None 
            }
    except Exception as e:
        print(f"❌ Image Search Error for '{query}': {e}")
        
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