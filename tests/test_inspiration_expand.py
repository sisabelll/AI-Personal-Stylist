import json
from core.config import Config
from services.client import OpenAIClient
from agents.inspiration_agent import InspirationAgent

def main():
    client = OpenAIClient()
    agent = InspirationAgent(client)

    user_profile = {
        "wear_preference": "womenswear",
        "preferences": {
            "style_icons": ["Bella Hadid", "Sofia Richie Grainge"],
            "favorite_brands": ["The Row", "Khaite", "Toteme"],
        },
    }

    expanded = agent.expand(user_profile)
    print("\n=== EXPANDED ===")
    print(json.dumps(expanded, indent=2))

    queries = agent.build_image_queries(expanded)
    print("\n=== QUERIES (first 10) ===")
    for q in queries[:10]:
        print("-", q)

if __name__ == "__main__":
    Config.validate()
    main()
