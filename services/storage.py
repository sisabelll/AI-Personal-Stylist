import json
import os
import time
from typing import Any, Dict


class DataLoader:
    """Load JSON files used by the app."""
    def __init__(self, base_dir: str = '.'):
        self.base_dir = base_dir
        self.user_profile = self._load('user_profile.json')
        self.style_rules = self._load('style_rules.json')
        self.trend_signals = self._load('trend_signals.json')
        self.request_context = self._load('request_context.json')
        self.request_context_input = self._load('request_context_input.json')
        self.golden_test_cases = self._load('golden_test_cases.json')
        self.conversation_state = self._load('conversation_state.json')
        
        self.snapshot_dir = os.path.join(self.base_dir, 'snapshots')
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def _load(self, filename: str) -> Any:
        path = os.path.join(self.base_dir, 'data', filename)
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Warning: {filename} not found at {path}. Returning empty dict.")
            return {}
        except json.JSONDecodeError as e:
            print(f"Warning: {filename} contains invalid JSON: {e}. Returning empty dict.")
            return {}
    
    def save_snapshot(self, context: Dict, state: Dict, filename: str = "debug_session.json") -> bool:
        """Saves current runtime state to the snapshots folder."""
        data = {
            "timestamp": time.time(),
            "context": context,
            "conversation_state": state
        }
        
        filepath = os.path.join(self.snapshot_dir, filename)
        
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"💾 Snapshot saved to {filepath}")
            return True
        except Exception as e:
            print(f"⚠️ Failed to save snapshot: {e}")
            return False

    def load_snapshot(self, filename: str = "debug_session.json") -> Dict:
        """Loads a runtime state from the snapshots folder."""
        filepath = os.path.join(self.snapshot_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"⚠️ Snapshot not found: {filepath}")
            return None

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            print(f"⚡ Snapshot loaded from {filepath}")
            return data
        except Exception as e:
            print(f"⚠️ Failed to load snapshot: {e}")
            return None