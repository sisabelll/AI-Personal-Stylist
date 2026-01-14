from serpapi import GoogleSearch
from core.config import Config
import concurrent.futures
import streamlit as st

# ---------------------------------------------------------
# THE CACHED SEARCHER (Standalone Function)
# ---------------------------------------------------------
# We keep this outside the class so Streamlit can cache it easily.
# If the same query comes in (e.g., "Reformation Navy Top"), 
# it returns the saved result instantly instead of calling Google.
@st.cache_data(show_spinner=False) 
def cached_google_shopping_search(api_key: str, query: str) -> dict:
    """
    Executes the actual API call to SerpApi. 
    Cached to prevent duplicate charges and latency.
    """
    if not api_key:
        return None

    params = {
        "api_key": api_key,
        "engine": "google_shopping",
        "q": query,
        "google_domain": "google.com",
        "gl": "us",  
        "hl": "en", 
        "num": 1     
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        
        # Extract the best match
        if "shopping_results" in results and results["shopping_results"]:
            item = results["shopping_results"][0]
            
            return {
                "title": item.get("title"),
                "image": item.get("thumbnail"),
                "price": item.get("price"),
                "link": item.get("link"),
                "source": item.get("source")
            }
            
    except Exception as e:
        print(f"❌ SerpApi Error for '{query}': {e}")
        
    return None


class CatalogClient:
    """
    Interface for fetching visual product data.
    Acts as a 'Digital Catalog' to find real-world images for outfit items.
    """

    def __init__(self):
        self.api_key = Config.SERPAPI_API_KEY
        if not self.api_key:
            print("⚠️ CatalogClient: No SERPAPI_API_KEY found. Visuals disabled.")
            return None

    def search_product(self, precise_query: str) -> dict:
        """
        Searches for a visual match for a specific item description.
        """
        return cached_google_shopping_search(self.api_key, precise_query)
    
    def search_products_parallel(self, items: list) -> dict:
        """
        Fetches images for a whole list of items simultaneously.
        """
        results = {}
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_item = {
                executor.submit(self.search_image, item.search_query): item.item_name
                for item in items
            }
            
            # Gather results as they finish
            for future in concurrent.futures.as_completed(future_to_item):
                item_name = future_to_item[future]
                try:
                    data = future.result()
                    results[item_name] = data
                except Exception as e:
                    print(f"❌ Error fetching {item_name}: {e}")
                    results[item_name] = None
                    
        return results