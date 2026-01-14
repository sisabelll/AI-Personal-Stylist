"""Orchestrator for the AI Personal Stylist project.

This file uses the smaller modules in the project. It will avoid making
OpenAI requests when no API key is configured and instead print the
intermediate data so you can iterate locally without spending API calls.
"""

import json
import os
import sys
import argparse
from pprint import pprint

from dotenv import load_dotenv

from data_loader import DataLoader
from client import OpenAIClient
from builders import StyleConstraintBuilder, ContextInterpreter
from stylist import StyleStylist
from manager import ConversationManager
from agents.style_researcher import StyleResearcherAgent

load_dotenv()


def run_interactive_session():
    """Run an interactive session where the user can specify style preferences."""
    base_dir = '.'
    data = DataLoader(base_dir)

    client = OpenAIClient()

    # Build deterministic style constraints
    constraint_builder = StyleConstraintBuilder(data.user_profile, data.style_rules)
    constraints = constraint_builder.build()

    # Prepare interpreter and stylist
    interpreter = ContextInterpreter(client, data.request_context)

    # If API is not configured, avoid calling LLM — print what we'd send instead
    if client.client is None:
        print('\nOPENAI_API_KEY not set — skipping LLM calls. Showing intermediate data:\n')
        print('User profile constraints:')
        pprint(constraints)
        print('\nRequest input (to be interpreted):')
        pprint(data.request_context_input)
        print('\nTo enable LLM calls, set OPENAI_API_KEY in your .env file or environment.')
        return

    # Initialize conversation manager
    manager = ConversationManager(
        client,
        data.user_profile,
        data.style_rules,
        data.request_context
    )

    # Initialize style researcher
    researcher = StyleResearcherAgent(client)

    print("\n🎨 Welcome to your AI Personal Stylist! 🎨")
    print("=" * 50)

    # Ask for style preference
    style_preference = input("\nWho or what style inspires you? (e.g., 'Carolyn Bessette-Kennedy', 'minimalist', 'bohemian', or press Enter to skip): ").strip()

    external_inspiration = None
    if style_preference:
        print(f"\n🕵️‍♀️ Researching style inspiration: {style_preference}")
        try:
            research_result = researcher.get_profile(style_preference)
            if research_result and 'error' not in research_result:
                external_inspiration = research_result
                print("✅ Style research complete!")
                print(f"Style vibe: {research_result.get('vibe', 'Unknown')}")
            else:
                print("❌ Research failed or returned no results. Continuing without external inspiration.")
        except Exception as e:
            print(f"❌ Error during research: {e}. Continuing without external inspiration.")

    # Inject research results into manager if available
    if external_inspiration:
        print("✅ Style research complete!")
        print(f"Style vibe: {external_inspiration.get('vibe', 'Unknown')}")
    else:
        external_inspiration = None

    # Start the conversation
    print("\n💬 Let's create your perfect outfit!")
    initial_query = input("What occasion or style are you looking for? (e.g., 'business meeting', 'date night', 'casual weekend'): ").strip()

    if not initial_query:
        initial_query = "Suggest a versatile everyday outfit"

    print(f"\n🎯 Generating recommendation for: {initial_query}")

    recommendation = manager.start_new_session(data.request_context_input, initial_query, external_inspiration)

    print('\n✨ OUTFIT RECOMMENDATION:\n')
    pprint(recommendation)

    # Interactive refinement loop
    while True:
        user_feedback = input("\n💭 What do you think? Any changes or feedback? (or 'quit' to exit): ").strip()

        if user_feedback.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Thanks for using your AI Personal Stylist! Goodbye!")
            break

        if user_feedback:
            print(f"\n🔄 Refining based on: '{user_feedback}'")
            refined_recommendation = manager.refine_session(user_feedback)
            print('\n✨ REFINED RECOMMENDATION:\n')
            pprint(refined_recommendation)
        else:
            print("No feedback provided. Keeping current recommendation.")


def main():
    base_dir = '.'
    data = DataLoader(base_dir)

    client = OpenAIClient()

    # Build deterministic style constraints
    constraint_builder = StyleConstraintBuilder(data.user_profile, data.style_rules)
    constraints = constraint_builder.build()

    # Prepare interpreter and stylist
    interpreter = ContextInterpreter(client, data.request_context)

    # If API is not configured, avoid calling LLM — print what we'd send instead
    if client.client is None:
        print('\nOPENAI_API_KEY not set — skipping LLM calls. Showing intermediate data:\n')
        print('User profile constraints:')
        pprint(constraints)
        print('\nRequest input (to be interpreted):')
        pprint(data.request_context_input)
        print('\nTo enable LLM calls, set OPENAI_API_KEY in your .env file or environment.')
        return

    situational_signals = interpreter.interpret(data.request_context_input)
    stylist_engine = StyleStylist(client)

    user_query = 'What should I wear to this event?'    
    recommendation = stylist_engine.recommend(constraints, situational_signals, user_query, closet_items=[])

    print('\nOUTFIT RECOMMENDATION:\n')
    pprint(recommendation)


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
    parser = argparse.ArgumentParser(description='AI Personal Stylist Orchestrator')
    parser.add_argument('--golden', action='store_true', help='Run golden test cases')
    parser.add_argument('--basic', action='store_true', help='Run basic recommendation (legacy)')
    
    args = parser.parse_args()
    
    if args.golden:
        run_golden_tests()
    elif args.basic:
        main()
    else:
        # Default to interactive mode
        run_interactive_session()