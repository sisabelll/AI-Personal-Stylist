import json
import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from client import OpenAIClient
from manager import ConversationManager
from fixtures import TEST_PROFILE, TEST_STYLE_RULES, TEST_REQUEST_CONTEXT

def run_canary_test(manager):
    print("🧪 Running Canary Test...")
    
    # 1. Inject Canary Logic (Mocking the KB load)
    manager.current_context['external_style_inspiration'] = {
        "vibe": "Neon-Gothic",
        "key_items": ["Radioactive Green Cardigan"]
    }
    
    # 2. Run Stylist
    response = manager._generate_recommendation("I want an outfit based on this style.")
    
    # 3. Assert
    if "Radioactive Green Cardigan" in response:
        print("✅ PASS: Canary item found in response. \n Response:", response)
        return True
    else:
        print(f"❌ FAIL: Response did not contain secret item.\nResponse: {response}")
        return False

def run_constraint_test(manager):
    print("🧪 Running Constraint Test...")
    
    # 1. Inject Constraint
    manager.current_context['external_style_inspiration'] = {
        "avoid": ["Denim"]
    }
    
    # 2. Run Stylist with a "Trap"
    response = manager._generate_recommendation("I want to wear my Denim Jacket.")
    
    # 3. Assert (We want the model to Push Back)
    if "avoid" in response.lower() or "instead" in response.lower() or "not" in response.lower():
         print("✅ PASS: Stylist resisted the constraint.")
         return True
    else:
         print("❌ FAIL: Stylist allowed the forbidden item.")
         return False

def setup_test_manager():
    """
    Creates a Manager instance with safe, dummy data.
    """
    client = OpenAIClient() 
    
    return ConversationManager(
        client=client,
        user_profile=TEST_PROFILE,    
        style_rules=TEST_STYLE_RULES,   
        request_context_schema=TEST_REQUEST_CONTEXT 
    )

if __name__ == "__main__":
    # Initialize properly
    manager = setup_test_manager()
    
    # Run tests
    run_canary_test(manager)
    run_constraint_test(manager)