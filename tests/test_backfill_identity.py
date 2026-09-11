"""
Regression tests for the two backfill defects found running it for real.

1. Two rows failed with "duplicate key value violates unique constraint
   uq_inspo_user_dedupe". Grouping hashed each row's CURRENT image_url, so a
   photo the pipeline had already mirrored carried a different identity from
   the same photo's un-mirrored row. They never grouped together, and the
   second one collided on write.

2. --prune-dead deleted any row whose image no longer fetched, feedback
   included. One of the live account's two 'the row' hide tombstones had a dead
   image; pruning it would have dropped that source to a single hide and
   silently emptied demoted.
"""
import importlib.util
import pathlib

import pytest

from services.image_identity import image_dedupe_key
from services.image_mirror import BUCKET_NAME

_spec = importlib.util.spec_from_file_location(
    "backfill", pathlib.Path("scripts/backfill_inspiration_images.py")
)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


ORIGINAL = "https://scontent-lga3-1.cdninstagram.com/v/t51.82787-15/671273771_18583239292028115_4572754363892836484_n.jpg?oe=690E1B2C"


def mirrored_url(original, user="u1", ext=".jpg"):
    """The URL mirror_image would produce for `original`."""
    return (f"https://proj.supabase.co/storage/v1/object/public/{BUCKET_NAME}/"
            f"{user}/{image_dedupe_key(original)}{ext}")


class TestIdentitySurvivesMirroring:
    def test_mirrored_row_keeps_the_original_photo_identity(self):
        assert backfill.identity_key(mirrored_url(ORIGINAL)) == image_dedupe_key(ORIGINAL)

    def test_mirrored_and_unmirrored_rows_group_together(self):
        """The exact collision: same photo, one row mirrored, one not."""
        assert backfill.identity_key(mirrored_url(ORIGINAL)) == backfill.identity_key(ORIGINAL)

    @pytest.mark.parametrize("ext", [".jpg", ".png", ".webp", ".avif"])
    def test_any_stored_extension_resolves(self, ext):
        assert backfill.identity_key(mirrored_url(ORIGINAL, ext=ext)) == image_dedupe_key(ORIGINAL)

    def test_query_string_on_the_mirrored_url_is_ignored(self):
        assert backfill.identity_key(mirrored_url(ORIGINAL) + "?t=123") == image_dedupe_key(ORIGINAL)

    def test_plain_urls_are_unchanged(self):
        plain = "https://www.net-a-porter.com/images/a.jpg"
        assert backfill.identity_key(plain) == image_dedupe_key(plain)

    def test_distinct_photos_stay_distinct_after_mirroring(self):
        other = ORIGINAL.replace("671273771", "999999999")
        assert backfill.identity_key(mirrored_url(ORIGINAL)) != backfill.identity_key(mirrored_url(other))

    def test_a_bucket_path_that_is_not_a_hash_falls_back(self):
        odd = (f"https://proj.supabase.co/storage/v1/object/public/{BUCKET_NAME}/u1/logo.png")
        assert backfill.identity_key(odd) == image_dedupe_key(odd)

    def test_empty_url(self):
        assert backfill.identity_key("") == ""
        assert backfill.identity_key(None) == ""


class TestPruneSpareFeedbackRows:
    """The partition --prune-dead applies: only feedback-free rows may go."""

    @staticmethod
    def partition(dead):
        keep = [r for r in dead if r.get("feedback")]
        prunable = [r for r in dead if not r.get("feedback")]
        return keep, prunable

    def test_hide_tombstone_is_never_pruned(self):
        dead = [
            {"id": "1", "feedback": "hide", "source_name": "the row"},
            {"id": "2", "feedback": None, "source_name": "the row"},
        ]
        keep, prunable = self.partition(dead)
        assert [r["id"] for r in keep] == ["1"]
        assert [r["id"] for r in prunable] == ["2"]

    def test_demotion_threshold_survives_a_prune(self):
        """Two hides for one source must still be two hides afterwards."""
        dead = [{"id": "1", "feedback": "hide", "source_name": "the row"}]
        alive = [{"id": "2", "feedback": "hide", "source_name": "the row"}]
        keep, prunable = self.partition(dead)
        remaining = keep + alive
        hides = [r for r in remaining if r["feedback"] == "hide" and r["source_name"] == "the row"]
        assert len(hides) >= 2, "demoted would have silently emptied"

    @pytest.mark.parametrize("fb", ["save", "like", "hide", "dislike"])
    def test_every_feedback_kind_is_protected(self, fb):
        keep, prunable = self.partition([{"id": "x", "feedback": fb}])
        assert len(keep) == 1 and prunable == []

    def test_untouched_rows_are_still_prunable(self):
        keep, prunable = self.partition([{"id": "a", "feedback": None},
                                         {"id": "b", "feedback": ""}])
        assert keep == [] and len(prunable) == 2
