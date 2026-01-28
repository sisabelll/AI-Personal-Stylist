import unittest

from agents.stylist import StyleStylist


def make_item(category: str, item_name: str):
    return {
        "category": category,
        "item_name": item_name,
        "search_query": f"{item_name} query",
        "reason": "test",
    }


def apply_swap(stylist: StyleStylist, old_items, new_items, swap_requests):
    # Mimic the key deterministic post-processing path in StyleStylist
    print(f"\n🧪 swap_requests: {swap_requests}")
    stabilized = stylist._stabilize_outfit(new_items, old_items, swap_requests)
    return stylist._enforce_one_piece_physics(stabilized)


def compute_swap_set(old_items, swap_requests):
    swap_set = {c for c in swap_requests if c}
    old_cats = {it.get("category") for it in (old_items or [])}
    if (("Top" in swap_set) or ("Bottom" in swap_set)) and ("OnePiece" in old_cats):
        swap_set |= {"OnePiece"}
    if "OnePiece" in swap_set:
        swap_set |= {"Top", "Bottom"}
    return swap_set


def onepiece_requested(swap_requests):
    return "OnePiece" in {c for c in swap_requests if c}


class TestSwapLogic(unittest.TestCase):
    def setUp(self):
        # client is unused for deterministic helpers
        self.stylist = StyleStylist(client=None)

    def test_swap_top_and_shoes_only(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Top", "New Top"),
            make_item("Bottom", "New Bottom (should be locked)"),
            make_item("Shoes", "New Shoes"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Top", "Shoes"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Top"]["item_name"], "New Top")
        self.assertEqual(by_cat["Shoes"]["item_name"], "New Shoes")
        self.assertEqual(by_cat["Bottom"]["item_name"], "Old Bottom")

    def test_onepiece_to_bottom_removes_onepiece(self):
        old_items = [
            make_item("OnePiece", "Old Dress"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Bottom", "New Pants"),
            make_item("Top", "New Sweater"),
            make_item("OnePiece", "New Dress (should be removed)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Bottom"])
        cats = {it["category"] for it in result}
        self.assertIn("Bottom", cats)
        self.assertIn("Top", cats)
        self.assertNotIn("OnePiece", cats)

    def test_onepiece_to_top_removes_onepiece(self):
        old_items = [
            make_item("OnePiece", "Old Dress"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Top", "New Sweater"),
            make_item("OnePiece", "New Dress (should be removed)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Top"])
        cats = {it["category"] for it in result}
        self.assertIn("Top", cats)
        self.assertNotIn("OnePiece", cats)

    def test_separates_to_onepiece_removes_top_bottom(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("OnePiece", "New Dress"),
            make_item("Top", "New Top (should be removed)"),
            make_item("Bottom", "New Bottom (should be removed)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["OnePiece"])
        cats = {it["category"] for it in result}
        self.assertIn("OnePiece", cats)
        self.assertNotIn("Top", cats)
        self.assertNotIn("Bottom", cats)

    def test_swap_bottom_without_top_still_removes_onepiece(self):
        old_items = [
            make_item("OnePiece", "Old Dress"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Bottom", "New Pants"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Bottom"])
        cats = {it["category"] for it in result}
        self.assertIn("Bottom", cats)
        self.assertIn("Top", cats)
        self.assertNotIn("OnePiece", cats)

    def test_idempotent_after_multiple_iterations(self):
        old_items = [
            make_item("OnePiece", "Old Dress"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Bottom", "New Pants"),
            make_item("Top", "New Sweater"),
        ]
        swap_requests = ["Bottom"]
        prev = apply_swap(self.stylist, old_items, new_items, swap_requests)
        for _ in range(10):
            curr = apply_swap(self.stylist, prev, prev, swap_requests)
            self.assertEqual(prev, curr)
            prev = curr

    def test_iterative_swap_sequence(self):
        # Start with a one-piece outfit
        state = [
            make_item("OnePiece", "Start Dress"),
            make_item("Shoes", "Start Shoes"),
            make_item("Accessory", "Start Necklace"),
        ]

        # 1) Swap to separates via Bottom request
        new_items = [
            make_item("Top", "New Sweater"),
            make_item("Bottom", "New Pants"),
            make_item("OnePiece", "New Dress (should be removed)"),
            make_item("Shoes", "New Shoes (should be locked)"),
        ]
        state = apply_swap(self.stylist, state, new_items, ["Bottom"])
        cats = {it["category"] for it in state}
        self.assertIn("Top", cats)
        self.assertIn("Bottom", cats)
        self.assertNotIn("OnePiece", cats)

        # 2) Swap shoes only
        new_items = [
            make_item("Top", "Top v2 (should be locked)"),
            make_item("Bottom", "Bottom v2 (should be locked)"),
            make_item("Shoes", "Shoes v2"),
            make_item("Accessory", "Accessory v2 (should be locked)"),
        ]
        state = apply_swap(self.stylist, state, new_items, ["Shoes"])
        by_cat = {it["category"]: it for it in state}
        self.assertEqual(by_cat["Shoes"]["item_name"], "Shoes v2")
        self.assertEqual(by_cat["Top"]["item_name"], "New Sweater")
        self.assertEqual(by_cat["Bottom"]["item_name"], "New Pants")

        # 3) Swap accessory + top together
        new_items = [
            make_item("Top", "Top v3"),
            make_item("Bottom", "Bottom v3 (should be locked)"),
            make_item("Shoes", "Shoes v3 (should be locked)"),
            make_item("Accessory", "Accessory v3"),
        ]
        state = apply_swap(self.stylist, state, new_items, ["Top", "Accessory"])
        by_cat = {it["category"]: it for it in state}
        self.assertEqual(by_cat["Top"]["item_name"], "Top v3")
        self.assertEqual(by_cat["Accessory"]["item_name"], "Accessory v3")
        self.assertEqual(by_cat["Bottom"]["item_name"], "New Pants")

        # 4) Swap to one-piece and ensure separates are dropped
        new_items = [
            make_item("OnePiece", "Final Dress"),
            make_item("Top", "Top v4 (should be removed)"),
            make_item("Bottom", "Bottom v4 (should be removed)"),
            make_item("Shoes", "Shoes v4"),
        ]
        state = apply_swap(self.stylist, state, new_items, ["OnePiece"])
        cats = {it["category"] for it in state}
        self.assertIn("OnePiece", cats)
        self.assertNotIn("Top", cats)
        self.assertNotIn("Bottom", cats)

    def test_deterministic_fuzz_swaps(self):
        rng = __import__("random").Random(1337)
        categories = ["Top", "Bottom", "Shoes", "Outerwear", "Accessory", "OnePiece"]

        def make_outfit(seed_label: str, use_onepiece: bool):
            items = [
                make_item("Shoes", f"{seed_label} Shoes"),
                make_item("Outerwear", f"{seed_label} Outerwear"),
                make_item("Accessory", f"{seed_label} Accessory"),
            ]
            if use_onepiece:
                items.append(make_item("OnePiece", f"{seed_label} OnePiece"))
            else:
                items.append(make_item("Top", f"{seed_label} Top"))
                items.append(make_item("Bottom", f"{seed_label} Bottom"))
            return items

        state = make_outfit("Init", use_onepiece=False)

        for i in range(25):
            # Pick 1-3 swap categories
            swap_requests = rng.sample(categories, rng.randint(1, 3))
            new_items = make_outfit(f"Step{i}", use_onepiece=rng.choice([True, False]))

            result = apply_swap(self.stylist, state, new_items, swap_requests)
            by_cat = {it["category"]: it for it in result}
            old_map = {it["category"]: it for it in state}

            swap_set = compute_swap_set(state, swap_requests)
            op_requested = onepiece_requested(swap_requests)

            # Invariant: OnePiece never coexists with Top/Bottom
            has_onepiece = "OnePiece" in by_cat
            if has_onepiece:
                self.assertNotIn("Top", by_cat)
                self.assertNotIn("Bottom", by_cat)

            # Locked categories must remain unchanged (except OnePiece dropped when switching to separates)
            for cat, old_it in old_map.items():
                if cat in swap_set:
                    continue
                if cat == "OnePiece" and (("Top" in swap_set) or ("Bottom" in swap_set)):
                    # Switching to separates can drop the one-piece
                    continue
                if cat in {"Top", "Bottom"} and op_requested:
                    # OnePiece explicitly requested drops Top/Bottom
                    continue
                self.assertIn(cat, by_cat)
                self.assertEqual(by_cat[cat]["item_name"], old_it["item_name"])

            state = result

    def test_swap_accessory_only(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Accessory", "Old Necklace"),
        ]
        new_items = [
            make_item("Top", "New Top (should be locked)"),
            make_item("Bottom", "New Bottom (should be locked)"),
            make_item("Accessory", "New Necklace"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Accessory"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Accessory"]["item_name"], "New Necklace")
        self.assertEqual(by_cat["Top"]["item_name"], "Old Top")
        self.assertEqual(by_cat["Bottom"]["item_name"], "Old Bottom")

    def test_swap_shoes_only(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Top", "New Top (should be locked)"),
            make_item("Bottom", "New Bottom (should be locked)"),
            make_item("Shoes", "New Shoes"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Shoes"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Shoes"]["item_name"], "New Shoes")
        self.assertEqual(by_cat["Top"]["item_name"], "Old Top")
        self.assertEqual(by_cat["Bottom"]["item_name"], "Old Bottom")

    def test_unknown_category_is_ignored(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
        ]
        new_items = [
            make_item("Mystery", "Weird Item"),
            make_item("Top", "New Top (should be locked)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Mystery"])
        cats = {it["category"] for it in result}
        # Unknown should not be added; locked items should remain.
        self.assertIn("Top", cats)
        self.assertIn("Bottom", cats)
        self.assertNotIn("Mystery", cats)

    def test_swap_outerwear_only(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Outerwear", "Old Coat"),
        ]
        new_items = [
            make_item("Top", "New Top (should be locked)"),
            make_item("Bottom", "New Bottom (should be locked)"),
            make_item("Outerwear", "New Coat"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Outerwear"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Outerwear"]["item_name"], "New Coat")
        self.assertEqual(by_cat["Top"]["item_name"], "Old Top")
        self.assertEqual(by_cat["Bottom"]["item_name"], "Old Bottom")

    def test_swap_top_and_bottom_together(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Top", "New Top"),
            make_item("Bottom", "New Bottom"),
            make_item("Shoes", "New Shoes (should be locked)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Top", "Bottom"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Top"]["item_name"], "New Top")
        self.assertEqual(by_cat["Bottom"]["item_name"], "New Bottom")
        self.assertEqual(by_cat["Shoes"]["item_name"], "Old Shoes")

    def test_onepiece_to_top_only_drops_onepiece(self):
        old_items = [
            make_item("OnePiece", "Old Dress"),
            make_item("Shoes", "Old Shoes"),
        ]
        new_items = [
            make_item("Top", "New Sweater"),
            make_item("OnePiece", "New Dress (should be removed)"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Top"])
        cats = {it["category"] for it in result}
        self.assertIn("Top", cats)
        self.assertNotIn("OnePiece", cats)

    def test_swap_accessory_and_shoes(self):
        old_items = [
            make_item("Top", "Old Top"),
            make_item("Bottom", "Old Bottom"),
            make_item("Shoes", "Old Shoes"),
            make_item("Accessory", "Old Necklace"),
        ]
        new_items = [
            make_item("Top", "New Top (should be locked)"),
            make_item("Bottom", "New Bottom (should be locked)"),
            make_item("Shoes", "New Shoes"),
            make_item("Accessory", "New Necklace"),
        ]
        result = apply_swap(self.stylist, old_items, new_items, ["Shoes", "Accessory"])
        by_cat = {it["category"]: it for it in result}
        self.assertEqual(by_cat["Shoes"]["item_name"], "New Shoes")
        self.assertEqual(by_cat["Accessory"]["item_name"], "New Necklace")
        self.assertEqual(by_cat["Top"]["item_name"], "Old Top")
        self.assertEqual(by_cat["Bottom"]["item_name"], "Old Bottom")


if __name__ == "__main__":
    unittest.main()
