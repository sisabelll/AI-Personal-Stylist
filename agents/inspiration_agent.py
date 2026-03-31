from typing import Dict, Any, List
from core.config import Config
from core.schemas import InspirationExpandLLM

class InspirationAgent:
    def __init__(self, client):
        self.client = client

    def expand(self, user_profile) -> Dict[str, Any]:
        prefs = user_profile.get("preferences") or {}
        icons = prefs.get("style_icons") or []
        brands = prefs.get("favorite_brands") or []
        wear = (user_profile.get("wear_preference") or "unisex").lower()

        system = (
            "You are a fashion research assistant.\n"
            "Given initial style icons and brands, expand into:\n"
            "- similar_icons: 6-10 names\n"
            "- motifs: 6-10 short, SEARCHABLE phrases (items/silhouettes/materials/styling moves)\n"
            "- brand_angles: 4-8 (how to search brands)\n\n"

            "OUTPUT CONTRACT (STRICT):\n"
            "Return STRICT JSON ONLY with exactly these keys: similar_icons, motifs, brand_angles.\n"
            "No extra keys. No markdown. No commentary.\n\n"

            "RULES — SIMILAR_ICONS:\n"
            "- Prefer people known for STREET STYLE / OFF-DUTY looks.\n"
            "- At least 4 must be strongly aligned with the seed lane (Bella/Sofia + The Row/Khaite/Toteme vibe).\n"
            "- Avoid random red-carpet-only picks.\n"
            "- Names only (no @handles).\n\n"

            "RULES — MOTIFS (MOST IMPORTANT):\n"
            "- Motifs must be CONCRETE and SEARCHABLE: include at least one GARMENT/ITEM noun "
            "(e.g., blazer, trench, loafer, slingback, skirt, denim, knit, tote).\n"
            "- Avoid vague vibe-only phrases like 'Parisian chic', 'minimal vibes', 'effortlessly chic'.\n"
            "- At least 3 motifs must be STYLING MOVES (not just basics). Examples:\n"
            "  'sheer black socks with loafers', 'tonal oatmeal layering (knit + wool + leather)', "
            "'longline blazer with short hem balance', 'espresso leather outerwear over ivory base'.\n"
            "- Includes must be 2-4 CONCRETE tokens; excludes must be 1-4 CONCRETE searchable negatives "
            "(e.g., 'logo', 'neon', 'chunky', 'distressed', 'boho'), not abstract adjectives.\n\n"

            "RULES — BRAND_ANGLES:\n"
            "- brand must be one of the seed brands.\n"
            "- angle should be one of: lookbook, campaign, runway, street_style, editorial, best_sellers.\n"
            "- query_hint MUST NOT repeat the brand name. It should be only the suffix/angle words.\n"
            "  Good query_hint examples: 'lookbook', 'campaign images', 'runway collection', 'street style', 'editorial feature'.\n"
            "  Bad query_hint examples: 'The Row lookbook styles', 'Khaite editorial features'.\n\n"

            "QUALITY BAR:\n"
            "- Keep everything modern and specific.\n"
            "- No filler items.\n"
        )

        user = {
            "wear_preference": wear,
            "seed_icons": icons,
            "seed_brands": brands,
        }

        parsed: InspirationExpandLLM = self.client.structured(
            model=Config.OPENAI_MODEL_FAST,
            system=system,
            user=user,
            response_model=InspirationExpandLLM,
            temperature=0.2,
            max_tokens=1200,
        )

        data = parsed.model_dump()

        # Post-validators that depend on runtime seeds (LLM can’t see your python validators)
        seed_brand_set = {b.strip().lower() for b in brands}
        data["brand_angles"] = [
            ba for ba in data["brand_angles"]
            if ba["brand"].strip().lower() in seed_brand_set
        ]

        # Defensive: if the model violated brand rule and filtering empties it, rebuild deterministic angles
        if not data["brand_angles"] and brands:
            data["brand_angles"] = [
                {"brand": b, "angle": "lookbook", "query_hint": "lookbook campaign runway", "priority": 2}
                for b in brands[:6]
            ]

        return {
            "seed_icons": icons,
            "seed_brands": brands,
            **data,
        }
    
    def build_brand_query(self, brand: str, hint: str) -> str:
        """
        Defensive helper to avoid duplicated brand tokens.
        """
        brand_l = brand.lower()
        hint = (hint or "").strip()

        # remove brand tokens from hint
        hint_clean = " ".join(
            w for w in hint.split()
            if w.lower() not in brand_l.split()
        )

        return f"{brand} {hint_clean} outfit".strip()

    def build_image_queries(self, expanded: Dict[str, Any]) -> List[Dict[str, str]]:
        queries = []

        icon_names = (expanded.get("seed_icons") or [])[:2] + [i["name"] for i in (expanded.get("similar_icons") or [])[:6]]
        for icon in icon_names:
            if not icon:
                continue
            queries.append({
                "source_type": "icon",
                "source_name": icon,
                "q": f'{icon} street style outfit 2024 2025 2026'
            })

        # brands
        for ba in (expanded.get("brand_angles") or [])[:6]:
            brand = ba.get("brand")
            hint = ba.get("query_hint") or ba.get("angle") or "lookbook"

            queries.append({
                "source_type": "brand",
                "source_name": brand,
                "q": self.build_brand_query(brand, hint),
            })

        # motifs
        for m in (expanded.get("motifs") or [])[:8]:
            phrase = m["phrase"]
            inc = " ".join(m.get("includes") or [])
            exc = " ".join([f"-{t}" for t in (m.get("excludes") or [])])
            queries.append({
                "source_type": "motif",
                "source_name": phrase,
                "q": f'{phrase} {inc} street style outfit inspiration 2024 2025 2026 {exc}'.strip()
            })

        return queries
