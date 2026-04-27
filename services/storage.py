import json
import os
from supabase import create_client, Client

class StorageService:
    def __init__(self):
        """
        Initializes the Supabase client using credentials from environment variables.
        """
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY")

        if not url or not key:
            raise EnvironmentError("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        
        self.supabase: Client = create_client(url, key)
        if service_key:
            self.db_admin: Client = create_client(url, service_key)
        else:
            self.db_admin = None
            print("⚠️ Warning: No Service Key found. Database writes might fail.")

    # ==========================================
    # 👤 USER PROFILES (Replaces user_profile.json)
    # ==========================================

    def get_profile(self, user_id: str):
        """
        Fetches the user's profile and merges it with their style preferences.
        Returns None if the user hasn't completed onboarding.
        """
        try:
            # 1. Get Static Stats (Height, Size, etc.)
            response = self.supabase.table('profiles').select("*").eq('id', user_id).execute()
            if response.data and len(response.data) > 0:
                profile = response.data[0]
                
                # 2. Get Vibe/Preferences (Icons, Brands)
                prefs = self._get_style_preferences(user_id)
                
                # 3. Merge them into one dictionary for the App to use
                if prefs:
                    profile['preferences'] = prefs
                return profile
            
            return None
        except Exception as e:
            print(f"Error fetching profile: {e}")
            return None

    def _get_style_preferences(self, user_id: str):
        """Internal helper to fetch style prefs."""
        try:
            response = self.supabase.table('style_preferences').select("*").eq('user_id', user_id).execute()
            return response.data[0] if response.data else None
        except Exception:
            return None

    def save_profile(self, user_id: str, profile_data: dict, preferences_data: dict, access_token: str):
        """Saves data using the Admin Client to bypass RLS issues."""
        try:
            # 🔐 SET AUTH HEADER
            # This tells Supabase: "I am User X, here is my badge."
            self.supabase.postgrest.auth(access_token)

            # 1. Save Profile
            profile_data['id'] = user_id
            self.supabase.table('profiles').upsert(profile_data).execute()

            # 2. Save Preferences
            preferences_data['user_id'] = user_id
            
            # Use explicit Select + Insert/Update logic
            existing = self.supabase.table('style_preferences').select("id").eq('user_id', user_id).execute()
            
            if existing.data:
                self.supabase.table('style_preferences').update(preferences_data).eq('user_id', user_id).execute()
            else:
                self.supabase.table('style_preferences').insert(preferences_data).execute()
                
            return True
        except Exception as e:
            print(f"Database Error: {e}")
            raise e

    # ==========================================
    # 👗 CLOSET (Future Feature)
    # ==========================================
    
    def get_closet(self, user_id: str):
        """Fetches all digital items owned by the user."""
        try:
            response = self.supabase.table('closet_items').select("*").eq('user_id', user_id).execute()
            return response.data
        except Exception as e:
            print(f"Error fetching closet: {e}")
            return []

    def add_closet_item(self, user_id: str, item_data: dict):
        """Adds a single item to the closet."""
        try:
            item_data['user_id'] = user_id
            self.supabase.table('closet_items').insert(item_data).execute()
            return True
        except Exception as e:
            print(f"Error adding item: {e}")
            return False
        
    # ==========================================
    # Revisions
    # ==========================================
    def insert_styling_revision(self, row: dict):
        """
        Inserts one revision event into Supabase.
        `row` must be JSON-serializable for jsonb fields.
        """
        return self.supabase.table("styling_revisions").insert(row).execute()
    
    def save_outfit_rating(self, user_id: str, revision_id: str, user_rating: int, user_saved: bool = False):
        """Updates a styling_revisions row with the user's star rating and saved flag."""
        try:
            self.supabase.table("styling_revisions").update({
                "user_rating": user_rating,
                "user_saved": user_saved,
            }).eq("id", revision_id).eq("user_id", user_id).execute()
            return True
        except Exception as e:
            print(f"Error saving outfit rating: {e}")
            return False

    def fetch_liked_outfits(self, user_id: str, limit: int = 20):
        """Fetch outfits the user rated 4+ stars or explicitly saved."""
        try:
            response = (
                self.supabase.table("styling_revisions")
                .select("id, user_query, final_outfit, final_score, user_rating, user_saved, style_tags, lessons, created_at")
                .eq("user_id", user_id)
                .or_("user_rating.gte.4,user_saved.eq.true")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception as e:
            print(f"Error fetching liked outfits: {e}")
            return []

    def fetch_low_rated_lessons(self, user_id: str, limit: int = 5):
        """Fetch outfits the user rated 1-2 stars to derive patterns to avoid."""
        try:
            response = (
                self.supabase.table("styling_revisions")
                .select("lessons, style_tags, user_rating")
                .eq("user_id", user_id)
                .lte("user_rating", 2)
                .not_.is_("user_rating", "null")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception as e:
            print(f"Error fetching low-rated lessons: {e}")
            return []

    def fetch_accepted_revisions(self, user_id: str, tags: list[str], limit: int = 5):
        q = (
            self.supabase.table("styling_revisions")
            .select("final_score, style_tags, lessons, version, created_at")
            .eq("user_id", str(user_id))
            .eq("accepted", True)
            .order("created_at", desc=True)
            .limit(limit)
        )

        if tags:
            tags = [t for t in tags if t][:3]
            conds = ",".join([f"style_tags.cs.{{{t}}}" for t in tags])
            q = q.or_(conds)

        return q.execute()

    # ==========================================
    # 📂 STATIC FILES (Preserving Old Functionality)
    # ==========================================

    def load_config(self, filename: str):
        """
        Helper to load static JSON files (like style_rules.json or trend_signals.json)
        that are NOT user-specific.
        """
        try:
            # Assuming 'data' folder exists at root
            path = os.path.join(os.getcwd(), 'data', filename)
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Could not load config {filename}: {e}")
            return {}