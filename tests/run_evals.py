import json
import argparse
import pprint
from core.client import OpenAIClient
from workflow.manager import ConversationManager
from services.storage import DataLoader

def run_golden_tests():
    """Run golden test cases and score the LLM outputs."""
    base_dir = '.'
    data = DataLoader(base_dir)
    client = OpenAIClient()

    if client.client is None:
        print('OPENAI_API_KEY not set — cannot run golden tests with LLM.')
        return

    test_cases = data.golden_test_cases
    results = []

    # Select user profile if it's a list
    selected_profile = data.user_profile
    if isinstance(data.user_profile, list):
        print("Available user profiles:")
        for i, profile in enumerate(data.user_profile):
            print(f"{i}: {profile.get('name', 'Unknown')}")
        try:
            choice = int(input("Choose a user profile (index): "))
            selected_profile = data.user_profile[choice]
        except (ValueError, IndexError):
            print("Invalid choice, using first profile.")
            selected_profile = data.user_profile[0]

    # Initialize conversation manager
    manager = ConversationManager(
        client, 
        selected_profile, 
        data.style_rules, 
        data.request_context
    )

    for case in test_cases[:2]:
        print(f"#### Request context: {case['name']} ####") # 1. Start Session (The Manager handles Interpretation internally)
        initial_user_query = case.get('user_query', 'Recommend me a suitable outfit.')
        recommendation_1 = manager.start_new_session(case['request_context'], initial_user_query)
        print('\nInitial Recommendation:')
        pprint(recommendation_1)

        # 2. Simulate User Feedback
        user_followup = input("Enter your feedback: ")
        print(f"\nUser says: '{user_followup}'")
        
        # 3. Refine Session (The Manager handles State Merging internally)
        recommendation_2 = manager.refine_session(user_followup)
        print('\nRefined Recommendation:')
        pprint(recommendation_2)

        # Refine once more
        user_followup2 = input("Enter your second feedback: ")
        print(f"\nUser says: '{user_followup2}'")
        recommendation_3 = manager.refine_session(user_followup2)

        print('\nRefined Recommendation (2nd):')
        pprint(recommendation_3)
        results.append({
            "case": case['name'],
            "initial": recommendation_1,
            "refined": recommendation_2,
            "refined_again": recommendation_3
        })

    # Save results to results.json
    with open('test_results/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print(f'\nSaved {len(results)} results to test_results/results.json')

    return results

if __name__ == '__main__':
    run_golden_tests()