from core.style_program_schemas import StyleProgram

class StyleProgramBuilder:
    def build(self, constraints: dict, situational_signals: dict, user_query: str, current_outfit=None) -> StyleProgram:
        color = constraints.get("personal_color", "General")
        body = constraints.get("body_style_essence", "General")
        season = constraints.get("season", "General")

        inspo = (situational_signals.get("external_inspiration") or {}).get("vibe", "")
        interp = situational_signals.get("style_interpretation", {})  # optional if you pass it in
        formality = interp.get("formality_level", "medium")
        tone = interp.get("social_tone", "polished")
        bias = interp.get("aesthetic_bias", "clean_chic")

        editorial_nos = []
        if bias in ["quiet_luxury", "clean_chic"]:
            editorial_nos += ["no fussy micro-prints", "no cheap-shine polyester", "avoid overly chunky shoes unless requested"]
        if tone in ["professional"]:
            editorial_nos += ["no distressed denim", "no overly revealing cuts"]
        if formality == "high":
            editorial_nos += ["no casual athleisure textures", "no overly casual totes"]

        style_brief = "\n".join([
            f"Vibe keywords: {bias}, {tone}" + (f", {inspo}" if inspo else ""),
            f"Silhouette: honor {body} lines; aim for clean proportion + leg-lengthening.",
            f"Palette: prioritize {color}; keep contrast controlled.",
            "Materials: prefer natural-looking textures; avoid flimsy fabric tells.",
            "Editorial rule: ONE hero element only (silhouette OR texture OR accessory).",
            f"Trend selectivity: max 1 current element; keep the rest timeless.",
            "NOs: " + "; ".join(editorial_nos[:4]) if editorial_nos else "NOs: avoid anything costume-y or dated."
        ])

        hard_constraints_summary = "\n".join([
            f"Season: {season}",
            "If editing: keep unchanged items EXACTLY (copy verbatim).",
            "Respect explicit swap/remove requests and event constraints."
        ])

        return StyleProgram(
            style_brief=style_brief,
            hard_constraints_summary=hard_constraints_summary,
            fail_checks=[
                "Violates personal color hard constraints",
                "Formality mismatch with event/time_of_day",
                "Edit-mode: changed locked categories/items",
                "One-piece dominance violated",
                "Too many statement items (trend soup)"
            ],
        )
