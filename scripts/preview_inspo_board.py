"""
Render the real inspiration-board component locally, with no Supabase.

The Python-side fixes are covered by tests/test_inspiration_dedupe.py. What
that can't show you is the board itself: whether duplicates are actually gone
and whether a dead image still leaves the header counting cards that aren't
there. This drives the real component file with a fixture built from URLs
captured off the live table during the investigation.

    PYTHONPATH=. python scripts/preview_inspo_board.py            # after the fix
    PYTHONPATH=. python scripts/preview_inspo_board.py --broken   # before the fix

--broken skips deduplication and restores the old silent img.onerror, so you can
see the two boards side by side.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import tempfile
import webbrowser

from services.image_identity import image_identity

COMPONENT = pathlib.Path("components/inspiration_board/frontend/index.html")

# Real rows from inspiration_items. The three net-a-porter URLs still resolve
# (they were timing out until the mirror's browser headers landed); the
# Instagram ones are the expired signatures that emptied the board, and they
# appear repeatedly under different edge hosts, which is what put the same
# photo on the board up to ten times.
_IG_PHOTO_A = "671273771_18583239292028115_4572754363892836484_n.jpg"
_IG_PHOTO_B = "657228158_18582636988003935_9084175833587828264_n.jpg"

FIXTURE = [
    # -- group 1: images as they look AFTER mirroring ---------------------
    # Stand-ins for the permanent Supabase Storage URLs upsert_items now
    # writes. Plain, unsigned, no hotlink protection — they just load.
    *[
        {"id": f"mirrored-{i}", "source_name": name, "tags": tags,
         "image_url": f"https://picsum.photos/seed/{seed}/{w}/{h}",
         "page_url": "https://www.instagram.com/p/DWQRhivlU9u/",
         "caption": caption, "saved": saved}
        for i, (seed, w, h, name, tags, caption, saved) in enumerate([
            ("stylist-a", 600, 800, "Bella Hadid", ["instagram", "street style"], "off-duty layering", False),
            ("stylist-b", 600, 900, "The Row", ["brand", "minimal"], "tailored coat", True),
            ("stylist-c", 600, 700, "Sofia Richie Grainge", ["instagram", "evening"], "evening look", False),
            ("stylist-d", 600, 850, "Toteme", ["brand", "knitwear"], "wool trousers", False),
            ("stylist-e", 600, 750, "Khaite", ["brand", "denim"], "raw hem denim", False),
            ("stylist-f", 600, 820, "Arket", ["brand", "basics"], "boxy shirt", False),
        ])
    ],
    # -- group 2: hotlink-protected, never mirrored ------------------------
    # Real rows from inspiration_items. These load in a normal browser and
    # stall in a headless one, which is the whole argument for mirroring:
    # a URL that works on your machine is not a URL that works everywhere.
    {"id": "hotlink-1", "source_name": "NET-A-PORTER", "tags": ["brand", "the row"],
     "image_url": "https://www.net-a-porter.com/variants/images/46376663162959538/in/w358_q60.jpg",
     "page_url": "https://www.net-a-porter.com/en-us/shop/new-in", "caption": "Tailored coat"},
    {"id": "hotlink-2", "source_name": "NET-A-PORTER", "tags": ["brand", "khaite"],
     "image_url": "https://www.net-a-porter.com/variants/images/46376663163028473/in/w358_q60.jpg",
     "page_url": "https://www.net-a-porter.com/en-us/shop/new-in", "caption": "Knit dress"},
    # -- group 3: one photo, five CDN edges: the duplicate bug -------------
    *[
        {"id": f"dupe-a-{i}", "source_name": "Bella Hadid", "tags": ["instagram"],
         "image_url": f"https://{host}/v/t51.82787-15/{_IG_PHOTO_A}?stp=dst-jpg_e35&oe=690E1B2C",
         "page_url": "https://www.instagram.com/p/DWQRhivlU9u/", "caption": "street style"}
        for i, host in enumerate([
            "scontent-lga3-1.cdninstagram.com",
            "scontent-ord5-2.cdninstagram.com",
            "scontent-iad3-2.cdninstagram.com",
            "instagram.fluk1-1.fna.fbcdn.net",
            "instagram.fcps4-2.fna.fbcdn.net",
        ])
    ],
    # -- a second photo, three edges --------------------------------------
    *[
        {"id": f"dupe-b-{i}", "source_name": "Sofia Richie Grainge", "tags": ["instagram"],
         "image_url": f"https://{host}/v/t51.82787-15/{_IG_PHOTO_B}?stp=dst-jpg_e35&oe=690E1B2C",
         "page_url": "https://www.instagram.com/p/DXhJp-cFEY6/", "caption": "evening look"}
        for i, host in enumerate([
            "scontent-atl3-1.cdninstagram.com",
            "scontent-hou1-1.cdninstagram.com",
            "scontent-mia3-2.cdninstagram.com",
        ])
    ],
]


def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = image_identity(it["image_url"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def to_component_items(rows):
    return [{
        "id": r["id"],
        "src": r["image_url"],
        "page_url": r.get("page_url"),
        "caption": r.get("caption"),
        "tags": r.get("tags") or [],
        "source_name": r.get("source_name"),
        "saved": bool(r.get("saved")),
    } for r in rows]


HARNESS = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Inspiration board preview — %(mode)s</title>
<style>
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'DM Sans',sans-serif;
         background:#FAF8F5; color:#1C1C1E; }
  header { padding:14px 20px; border-bottom:1px solid #E5DDD5; background:#fff;
            display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  h1 { font-size:0.95rem; font-weight:500; margin:0; }
  .badge { font-size:0.7rem; letter-spacing:0.08em; text-transform:uppercase;
            padding:3px 10px; border-radius:99px; }
  .fixed { background:#E7F3EC; color:#1E6B3F; }
  .broken { background:#FBE9E7; color:#A5342A; }
  .stat { font-size:0.78rem; color:#6A6560; }
  .stat b { color:#1C1C1E; font-weight:500; }
  #log { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.72rem;
          color:#6A6560; padding:8px 20px; border-bottom:1px solid #E5DDD5;
          background:#fff; min-height:1.2em; }
  iframe { width:100%%; border:0; display:block; }
  .wrap { padding:16px 20px 40px; }
</style></head>
<body>
<header>
  <h1>Inspiration board</h1>
  <span class="badge %(badge_class)s">%(mode)s</span>
  <span class="stat"><b>%(sent)s</b> items sent to the component
    &nbsp;·&nbsp; %(note)s</span>
</header>
<div id="log">component events appear here &mdash; hover a card, or click ♡ / ✕ / ↻</div>
<div class="wrap"><iframe id="board" src="%(component)s"></iframe></div>
<script>
  const ITEMS = %(items)s;
  const frame = document.getElementById('board');
  const log = document.getElementById('log');

  // Stand in for Streamlit's component host: deliver the render message the
  // same way, and honour setFrameHeight so the masonry board isn't clipped.
  window.addEventListener('message', (e) => {
    const d = e.data || {};
    if (d.type === 'streamlit:componentReady') {
      frame.contentWindow.postMessage(
        { type: 'streamlit:render', args: { items: ITEMS } }, '*');
      log.textContent = 'streamlit:render -> ' + ITEMS.length + ' items';
    } else if (d.type === 'streamlit:setFrameHeight') {
      frame.style.height = (d.height || 600) + 'px';
    } else if (d.type === 'streamlit:setComponentValue') {
      log.textContent = 'setComponentValue  ' + JSON.stringify(d.value);
    }
  });
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broken", action="store_true",
                    help="skip dedupe and restore the silent img.onerror (pre-fix board)")
    ap.add_argument("--no-open", action="store_true", help="just print the path")
    ap.add_argument("--out-dir", help="where to write the preview (default: system temp)")
    args = ap.parse_args()

    if not COMPONENT.exists():
        print(f"ERROR: {COMPONENT} not found — run from the repo root.")
        return 1

    rows = FIXTURE if args.broken else dedupe(FIXTURE)
    items = to_component_items(rows)

    out_dir = pathlib.Path(args.out_dir or tempfile.gettempdir()) / "inspo_preview"
    out_dir.mkdir(parents=True, exist_ok=True)

    component_src = COMPONENT.read_text()
    if args.broken:
        # Put back the exact pre-fix behaviour: card disappears, count doesn't move.
        component_src = component_src.replace(
            "img.addEventListener('error', () => { pin.remove(); updateSub(); setHeight(); });",
            "img.addEventListener('error', () => { pin.remove(); setHeight(); });",
        )
    component_path = out_dir / ("component_broken.html" if args.broken else "component_fixed.html")
    component_path.write_text(component_src)

    unique = len({image_identity(r["image_url"]) for r in FIXTURE})
    note = (f"fixture holds {len(FIXTURE)} rows for {unique} distinct photos"
            if args.broken else
            f"{len(FIXTURE)} rows collapsed to {unique} distinct photos")

    page = HARNESS % {
        "mode": "pre-fix" if args.broken else "fixed",
        "badge_class": "broken" if args.broken else "fixed",
        "sent": len(items),
        "note": note,
        "component": component_path.name,
        "items": json.dumps(items),
    }
    out = out_dir / ("preview_broken.html" if args.broken else "preview_fixed.html")
    out.write_text(page)

    print(f"fixture rows      : {len(FIXTURE)}")
    print(f"distinct photos   : {unique}")
    print(f"sent to component : {len(items)}")
    mirrored = sum(1 for i in items if "picsum" in i["src"])
    hotlink = sum(1 for i in items if "net-a-porter" in i["src"])
    dead = len(items) - mirrored - hotlink
    print(f"  mirrored (load) : {mirrored}")
    print(f"  hotlinked       : {hotlink}  (load in a real browser, stall headless)")
    print(f"  expired IG      : {dead}  (403 — these get removed by img.onerror)")
    print()
    print(f"open: {out}")
    if not args.no_open:
        webbrowser.open(f"file://{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
