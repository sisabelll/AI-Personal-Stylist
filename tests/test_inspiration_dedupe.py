"""
Regression tests for the two inspiration-board bugs:

  1. The same photo appeared on the board up to ten times.
  2. The board rendered almost no images at all.

Both trace back to treating an Instagram CDN URL as a photo identity. These
URLs rotate their edge host on every scrape and carry an expiring signature, so
`sha1(scheme + host + path)` produced a fresh dedupe_key each run and the upsert
inserted instead of updated.

The URLs below are real rows pulled from the `inspiration_items` table while
investigating: one photo, ten hostnames, ten dedupe_keys, four pipeline runs.
"""
import pytest

from services.image_identity import image_identity, image_dedupe_key, is_instagram_cdn
from services.inspiration_store import InspirationStore


# One photo (media 18583239292028115) as stored ten times over four runs.
SAME_PHOTO_DIFFERENT_EDGES = [
    "https://scontent-lga3-1.cdninstagram.com/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_n.jpg?stp=dst-jpg_e35&oe=690E1B2C",
    "https://scontent-ord5-2.cdninstagram.com/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_n.jpg?stp=dst-jpg_e35&oe=6912AA01",
    "https://scontent-iad3-2.cdninstagram.com/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_n.jpg?stp=dst-jpg_p1080x1080&oe=69200000",
    "https://instagram.fluk1-1.fna.fbcdn.net/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_n.jpg?stp=other&oe=69311111",
    "https://instagram.fcps4-2.fna.fbcdn.net/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_s.jpg?oe=69422222",
]

DIFFERENT_PHOTO = (
    "https://scontent-lga3-1.cdninstagram.com/v/t51.82787-15/"
    "657228158_18582636988003935_9084175833587828264_n.jpg?stp=dst-jpg_e35&oe=690E1B2C"
)


class TestImageIdentity:
    def test_rotating_edge_hosts_collapse_to_one_key(self):
        keys = {image_dedupe_key(u) for u in SAME_PHOTO_DIFFERENT_EDGES}
        assert len(keys) == 1, f"expected 1 identity, got {len(keys)}"

    def test_size_variant_suffix_does_not_fork_identity(self):
        n = image_identity(SAME_PHOTO_DIFFERENT_EDGES[0])
        s = image_identity(SAME_PHOTO_DIFFERENT_EDGES[4])  # _s.jpg instead of _n.jpg
        assert n == s

    def test_distinct_photos_stay_distinct(self):
        assert image_identity(DIFFERENT_PHOTO) != image_identity(SAME_PHOTO_DIFFERENT_EDGES[0])

    def test_identity_ignores_expiring_signature(self):
        base = "https://scontent-lga3-1.cdninstagram.com/v/t51.82787-15/1111111_2222222_3333333_n.jpg"
        assert image_identity(base + "?oe=690E1B2C") == image_identity(base + "?oe=FFFFFFFF")

    def test_non_instagram_urls_keep_their_host(self):
        a = image_identity("https://www.net-a-porter.com/images/a.jpg?v=1")
        b = image_identity("https://cdn.example.com/images/a.jpg?v=1")
        assert a != b
        # ...but www. and the query are still normalised away
        assert a == image_identity("https://net-a-porter.com/images/a.jpg?v=2")

    def test_empty_url_yields_empty_identity(self):
        assert image_identity("") == ""
        assert image_identity(None) == ""
        assert image_dedupe_key("") == ""

    def test_is_instagram_cdn_covers_both_spellings(self):
        assert is_instagram_cdn("https://scontent-lga3-1.cdninstagram.com/x.jpg")
        assert is_instagram_cdn("https://instagram.fluk1-1.fna.fbcdn.net/x.jpg")
        assert not is_instagram_cdn("https://www.net-a-porter.com/x.jpg")


# --------------------------------------------------------------------------
# Fake Supabase client: records upserts and deletes without touching network
# --------------------------------------------------------------------------

class FakeQuery:
    def __init__(self, table):
        self._table = table
        self._filters = []

    def eq(self, col, val):
        self._filters.append(("eq", col, val)); return self

    def contains(self, col, val):
        self._filters.append(("contains", col, val)); return self

    def like(self, col, val):
        self._filters.append(("like", col, val)); return self

    def execute(self):
        matched = [r for r in self._table.rows if self._matches(r)]
        for r in matched:
            self._table.rows.remove(r)
        self._table.deletes.append({"filters": list(self._filters), "removed": len(matched)})
        return type("Resp", (), {"data": matched})()

    def _matches(self, row):
        for kind, col, val in self._filters:
            actual = row.get(col)
            if kind == "eq" and actual != val:
                return False
            if kind == "contains" and not set(val).issubset(set(actual or [])):
                return False
            if kind == "like" and val.strip("%") not in (actual or ""):
                return False
        return True


class FakeTable:
    def __init__(self):
        self.rows = []
        self.deletes = []
        self.upsert_calls = 0

    def upsert(self, rows, on_conflict=None):
        self.upsert_calls += 1
        key_cols = [c.strip() for c in (on_conflict or "").split(",") if c.strip()]
        for row in rows:
            existing = None
            if key_cols:
                for r in self.rows:
                    if all(r.get(c) == row.get(c) for c in key_cols):
                        existing = r
                        break
            if existing is not None:
                existing.update(row)
            else:
                self.rows.append(dict(row))
        return type("Exec", (), {"execute": lambda _self=None: type("Resp", (), {"data": rows})()})()

    def delete(self):
        return FakeQuery(self)


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return self.tables.setdefault(name, FakeTable())


class FakeStorageService:
    def __init__(self):
        self.supabase = FakeSupabase()
        self.db_admin = self.supabase


@pytest.fixture
def store():
    return InspirationStore(FakeStorageService())


def _ig_item(image_url, source_type="icon", source_name="Bella Hadid"):
    """Shaped exactly like the Instagram stage of inspiration_agent.run()."""
    return {
        "source_type": source_type,
        "source_name": source_name,
        "image_url": image_url,
        "page_url": "https://www.instagram.com/p/DWQRhivlU9u/",
        "caption": "",
        "tags": ["instagram"],
        "score": 0.7,
    }


class TestUpsertDeduplication:
    def test_repeat_scrapes_of_one_photo_produce_one_row(self, store):
        """Four pipeline runs, four CDN edges, one photo -> one row."""
        for url in SAME_PHOTO_DIFFERENT_EDGES:
            store.upsert_items("user-1", [_ig_item(url)], mirror=False)

        rows = store.supabase.table("inspiration_items").rows
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
        assert len({r["dedupe_key"] for r in rows}) == 1

    def test_distinct_photos_still_produce_distinct_rows(self, store):
        store.upsert_items("user-1", [_ig_item(SAME_PHOTO_DIFFERENT_EDGES[0])], mirror=False)
        store.upsert_items("user-1", [_ig_item(DIFFERENT_PHOTO)], mirror=False)
        assert len(store.supabase.table("inspiration_items").rows) == 2

    def test_within_one_batch_duplicates_collapse(self, store):
        store.upsert_items("user-1", [_ig_item(u) for u in SAME_PHOTO_DIFFERENT_EDGES], mirror=False)
        assert len(store.supabase.table("inspiration_items").rows) == 1

    def test_different_users_do_not_collide(self, store):
        url = SAME_PHOTO_DIFFERENT_EDGES[0]
        store.upsert_items("user-1", [_ig_item(url)], mirror=False)
        store.upsert_items("user-2", [_ig_item(url)], mirror=False)
        assert len(store.supabase.table("inspiration_items").rows) == 2


class TestInstagramPurge:
    def test_purge_removes_rows_the_instagram_stage_actually_writes(self, store):
        """
        The Instagram stage writes source_type 'icon'/'brand' — never
        'instagram' — so the old purge matched nothing and every run stacked
        another copy of the same posts.
        """
        store.upsert_items("user-1", [
            _ig_item(SAME_PHOTO_DIFFERENT_EDGES[0], source_type="icon"),
            _ig_item(DIFFERENT_PHOTO, source_type="brand", source_name="The Row"),
        ], mirror=False)
        assert len(store.supabase.table("inspiration_items").rows) == 2

        store.delete_instagram_items("user-1")
        assert store.supabase.table("inspiration_items").rows == []

    def test_purge_leaves_web_results_alone(self, store):
        store.upsert_items("user-1", [_ig_item(SAME_PHOTO_DIFFERENT_EDGES[0])], mirror=False)
        store.upsert_items("user-1", [{
            "source_type": "brand",
            "source_name": "The Row",
            "image_url": "https://www.net-a-porter.com/images/a.jpg",
            "page_url": "https://www.net-a-porter.com/shop",
            "caption": "",
            "tags": ["brand", "the row"],
            "score": 0.4,
        }], mirror=False)

        store.delete_instagram_items("user-1")
        rows = store.supabase.table("inspiration_items").rows
        assert len(rows) == 1
        assert "net-a-porter" in rows[0]["image_url"]

    def test_purge_removes_legacy_rows_without_the_instagram_tag(self, store):
        """Rows written before the tag existed still carry a CDN image_url."""
        legacy = _ig_item(SAME_PHOTO_DIFFERENT_EDGES[0])
        legacy["tags"] = []
        store.upsert_items("user-1", [legacy], mirror=False)

        store.delete_instagram_items("user-1")
        assert store.supabase.table("inspiration_items").rows == []

    def test_purge_scopes_to_one_user(self, store):
        store.upsert_items("user-1", [_ig_item(SAME_PHOTO_DIFFERENT_EDGES[0])], mirror=False)
        store.upsert_items("user-2", [_ig_item(SAME_PHOTO_DIFFERENT_EDGES[0])], mirror=False)

        store.delete_instagram_items("user-1")
        rows = store.supabase.table("inspiration_items").rows
        assert len(rows) == 1 and rows[0]["user_id"] == "user-2"
