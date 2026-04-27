import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ComponentProps,
  Streamlit,
  withStreamlitConnection,
} from "streamlit-component-lib";

// ── Types ────────────────────────────────────────────────────────────────────

interface InspirationItem {
  id: string;
  src: string; // base64 data URI
  page_url?: string;
  caption?: string;
  tags?: string[];
  source_name?: string;
}

// ── Global styles (injected once) ────────────────────────────────────────────

const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: transparent; font-family: 'DM Sans', sans-serif; }

  /* ── Masonry board ───────────────────────────────────────── */
  .pin-board {
    columns: 4;
    column-gap: 10px;
    padding: 2px 0;
  }
  @media (max-width: 960px)  { .pin-board { columns: 3; } }
  @media (max-width: 640px)  { .pin-board { columns: 2; } }

  /* ── Individual card ─────────────────────────────────────── */
  .pin-card {
    break-inside: avoid;
    margin-bottom: 10px;
    border-radius: 16px;
    overflow: hidden;
    position: relative;
    background: #ede7df;
    cursor: default;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .pin-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
    z-index: 2;
  }
  .pin-card img {
    width: 100%;
    display: block;
    transition: opacity 0.3s ease;
  }

  /* ── Hover overlay ───────────────────────────────────────── */
  .pin-overlay {
    position: absolute;
    inset: 0;
    background: linear-gradient(
      180deg,
      rgba(0, 0, 0, 0.38) 0%,
      transparent 38%,
      rgba(0, 0, 0, 0.45) 100%
    );
    opacity: 0;
    transition: opacity 0.2s ease;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 10px;
    pointer-events: none;
  }
  .pin-card:hover .pin-overlay {
    opacity: 1;
    pointer-events: all;
  }

  /* ── Action buttons ──────────────────────────────────────── */
  .pin-btn {
    background: rgba(255, 255, 255, 0.2);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    border: none;
    border-radius: 50%;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    color: #fff;
    font-size: 14px;
    line-height: 1;
    text-decoration: none;
    flex-shrink: 0;
    transition: background 0.15s ease, transform 0.12s ease;
  }
  .pin-btn:hover {
    background: rgba(255, 255, 255, 0.35);
    transform: scale(1.12);
  }
  .pin-btn.saved {
    background: #C9A96E;
  }
  .pin-btn.saved:hover {
    background: #b8924f;
  }

  /* ── Tag pills ───────────────────────────────────────────── */
  .pin-tag {
    font-size: 0.58rem;
    letter-spacing: 0.06em;
    text-transform: lowercase;
    background: rgba(255, 255, 255, 0.2);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    color: #fff;
    padding: 2px 8px;
    border-radius: 99px;
    white-space: nowrap;
    font-family: 'DM Sans', sans-serif;
  }

  /* ── Source label (visible at rest, hides on hover) ─────── */
  .pin-source {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 20px 10px 8px;
    background: linear-gradient(transparent, rgba(0, 0, 0, 0.38));
    pointer-events: none;
    transition: opacity 0.2s ease;
  }
  .pin-card:hover .pin-source { opacity: 0; }
  .pin-source span {
    color: rgba(255, 255, 255, 0.6);
    font-size: 0.58rem;
    letter-spacing: 0.08em;
    font-family: 'DM Sans', sans-serif;
  }

  /* ── Skeleton shimmer ────────────────────────────────────── */
  @keyframes shimmer {
    0%   { background-position: -500px 0; }
    100% { background-position:  500px 0; }
  }
  .skeleton {
    background: linear-gradient(
      90deg,
      #e8e0d8 25%,
      #f2ede8 50%,
      #e8e0d8 75%
    );
    background-size: 500px 100%;
    animation: shimmer 1.4s infinite linear;
  }

  /* ── Board header ────────────────────────────────────────── */
  .board-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18px;
    font-family: 'DM Sans', sans-serif;
  }
  .board-eyebrow {
    font-size: 0.62rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #C9A96E;
    margin-bottom: 4px;
  }
  .board-sub {
    font-size: 0.78rem;
    color: #9C9590;
  }
  .board-refresh {
    background: transparent;
    border: 1px solid #E5DDD5;
    border-radius: 8px;
    padding: 0.3rem 0.9rem;
    font-size: 0.74rem;
    color: #6A6560;
    cursor: pointer;
    font-family: 'DM Sans', sans-serif;
    letter-spacing: 0.05em;
    transition: border-color 0.15s, color 0.15s;
  }
  .board-refresh:hover {
    border-color: #C9A96E;
    color: #9B7740;
  }

  /* ── Empty state ─────────────────────────────────────────── */
  .empty-state {
    padding: 3rem;
    text-align: center;
    color: #9C9590;
    font-size: 0.88rem;
    font-family: 'DM Sans', sans-serif;
    letter-spacing: 0.02em;
  }
`;

// ── PinCard ───────────────────────────────────────────────────────────────────

interface PinCardProps {
  item: InspirationItem;
  isSaved: boolean;
  onSave: () => void;
  onHide: () => void;
}

function PinCard({ item, isSaved, onSave, onHide }: PinCardProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  if (failed) return null;

  return (
    <div className="pin-card">
      {/* Skeleton shown while image loads */}
      {!loaded && (
        <div className="skeleton" style={{ height: 220 }} />
      )}

      <img
        src={item.src}
        alt={item.caption ?? ""}
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        style={{
          opacity: loaded ? 1 : 0,
          // keep in flow once loaded; hide off-screen while loading
          position: loaded ? "static" : "absolute",
          top: 0,
          left: 0,
        }}
      />

      <div className="pin-overlay">
        {/* Top row: dismiss button */}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            className="pin-btn"
            onClick={onHide}
            title="Hide"
            style={{ fontSize: 12 }}
          >
            ✕
          </button>
        </div>

        {/* Bottom row: tags + actions */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
          {/* Tag pills */}
          <div
            style={{
              flex: 1,
              display: "flex",
              flexWrap: "wrap",
              gap: 4,
              overflow: "hidden",
              maxHeight: 44,
            }}
          >
            {(item.tags ?? []).slice(0, 3).map((tag) => (
              <span key={tag} className="pin-tag">
                {tag}
              </span>
            ))}
          </div>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
            {item.page_url && (
              <a
                className="pin-btn"
                href={item.page_url}
                target="_blank"
                rel="noopener noreferrer"
                title="Open source"
                onClick={(e) => e.stopPropagation()}
              >
                ↗
              </a>
            )}
            <button
              className={`pin-btn${isSaved ? " saved" : ""}`}
              onClick={onSave}
              title={isSaved ? "Saved" : "Save to style DNA"}
              style={{ fontSize: 16 }}
            >
              {isSaved ? "♥" : "♡"}
            </button>
          </div>
        </div>
      </div>

      {/* Source label — always visible at rest */}
      {item.source_name && (
        <div className="pin-source">
          <span>{item.source_name}</span>
        </div>
      )}
    </div>
  );
}

// ── InspirationBoard ──────────────────────────────────────────────────────────

function InspirationBoard({ args }: ComponentProps) {
  const items: InspirationItem[] = args?.items ?? [];
  const boardRef = useRef<HTMLDivElement>(null);

  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [saved, setSaved] = useState<Set<string>>(new Set());

  // Keep iframe height in sync with content — debounced so CSS hover
  // transitions don't trigger a resize loop via setFrameHeight.
  useEffect(() => {
    if (!boardRef.current) return;
    let raf: number;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => Streamlit.setFrameHeight());
    });
    ro.observe(boardRef.current);
    return () => { ro.disconnect(); cancelAnimationFrame(raf); };
  }, []);

  const handleSave = useCallback((id: string) => {
    setSaved((prev) => new Set([...prev, id]));
    Streamlit.setComponentValue({ action: "save", id });
  }, []);

  const handleHide = useCallback((id: string) => {
    setDismissed((prev) => new Set([...prev, id]));
    Streamlit.setComponentValue({ action: "hide", id });
  }, []);

  const handleRefresh = useCallback(() => {
    Streamlit.setComponentValue({ action: "refresh", id: null });
  }, []);

  const visible = items.filter((it) => !dismissed.has(it.id));

  return (
    <div ref={boardRef} style={{ padding: "2px 0 16px" }}>
      <style>{GLOBAL_CSS}</style>

      {/* Header */}
      <div className="board-header">
        <div>
          <div className="board-eyebrow">✦ &nbsp; Inspiration Board</div>
          <div className="board-sub">
            {visible.length} items &nbsp;·&nbsp; save what speaks to you, hide what doesn't
          </div>
        </div>
        <button className="board-refresh" onClick={handleRefresh}>
          ↻ &nbsp; Refresh
        </button>
      </div>

      {/* Grid or empty state */}
      {visible.length === 0 ? (
        <div className="empty-state">
          No items to show · try refreshing
        </div>
      ) : (
        <div className="pin-board">
          {visible.map((item) => (
            <PinCard
              key={item.id}
              item={item}
              isSaved={saved.has(item.id)}
              onSave={() => handleSave(item.id)}
              onHide={() => handleHide(item.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default withStreamlitConnection(InspirationBoard);
