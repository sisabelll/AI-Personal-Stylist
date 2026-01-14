from tavily import TavilyClient
import os

class SearchTool:
    def __init__(self):
        self.client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

    def search_web(self, query: str, max_results=5):
        """
        Executes a search and returns clean list of results.
        """
        try:
            print(f"🔎 Searching web for: {query}")
            response = self.client.search(
                query=query, 
                search_depth="advanced", 
                max_results=max_results
            )
            return response['results']
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []