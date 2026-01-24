class OutfitQA:
    ONE_PIECE = ("dress", "gown", "jumpsuit", "romper", "overalls")

    def check(self, recommendation: dict) -> dict:
        try:
            options = recommendation.get("outfit_options") or []
            if not options:
                return {"passed": False, "reason": "No outfit options."}

            items = (options[0].get("items") or [])
            if len(items) < 4:
                return {"passed": False, "reason": "Fewer than 4 items."}

            # one-piece dominance heuristic
            has_one_piece = any(any(k in (it.get("item_name","").lower()) for k in self.ONE_PIECE) for it in items)
            if has_one_piece:
                has_top = any((it.get("category","").lower() == "top") for it in items)
                has_bottom = any((it.get("category","").lower() == "bottom") for it in items)
                if has_top or has_bottom:
                    return {"passed": False, "reason": "One-piece with top/bottom present."}

            return {"passed": True}
        except Exception as e:
            return {"passed": False, "reason": str(e)}
