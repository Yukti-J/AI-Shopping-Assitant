import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

const PRIORITIES = [
  { id: "best_value", icon: "◈", label: "Best value", description: "A smart balance of price, ratings and reviews" },
  { id: "premium", icon: "✦", label: "Premium look", description: "A richer, more elevated choice" },
  { id: "quality", icon: "◇", label: "Quality", description: "Put product quality and feedback first" },
  { id: "lowest_price", icon: "↓", label: "Lowest price", description: "Keep the spend as low as possible" },
  { id: "best_reviews", icon: "★", label: "Best reviews", description: "Lean on ratings and review volume" },
  { id: "early_delivery", icon: "⚡", label: "Early delivery", description: "Get it to you as fast as possible" },
];

const formatPrice = (price) => {
  if (price === null || price === undefined) return "Price unavailable";
  return `₹${Math.round(price).toLocaleString("en-IN")}`;
};

const formatCount = (count) => {
  if (count === null || count === undefined) return "";
  if (count >= 100000) return `${(count / 100000).toFixed(1)}L`;
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`;
  return count.toString();
};

function App() {
  const [step, setStep] = useState("search");
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [parsedQuery, setParsedQuery] = useState(null);
  const [discovery, setDiscovery] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [priorities, setPriorities] = useState([]);
  // Platforms come from GET /api/search/platforms (backend TARGET_RETAILERS),
  // so the UI can never offer a platform the backend doesn't support.
  const [platforms, setPlatforms] = useState([]);
  const [platformsStatus, setPlatformsStatus] = useState("loading"); // "loading" | "ready" | "error"
  const [selectedPlatforms, setSelectedPlatforms] = useState([]);
  const [pincode, setPincode] = useState("");
  const [comparison, setComparison] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState("");
  const [error, setError] = useState("");

  const selectedProducts = useMemo(
    () => discovery.filter((p) => selectedIds.includes(p.id)),
    [discovery, selectedIds]
  );

  async function api(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Something went wrong. Please try again.");
    }
    return data;
  }

  async function loadPlatforms() {
    setPlatformsStatus("loading");
    try {
      const data = await api("/api/search/platforms");
      const list = data.platforms || [];
      if (list.length === 0) throw new Error("No platforms configured");
      setPlatforms(list);
      setSelectedPlatforms(list.map((p) => p.id)); // all selected by default
      setPlatformsStatus("ready");
    } catch {
      setPlatformsStatus("error");
    }
  }

  useEffect(() => {
    loadPlatforms();
  }, []);

  async function handleDiscover(event) {
    event?.preventDefault();
    if (query.trim().length < 2) return;
    setLoading(true);
    setLoadingLabel("Finding a few different styles for you…");
    setError("");
    try {
      const data = await api("/api/search/discover", {
        method: "POST",
        body: JSON.stringify({ query: query.trim() }),
      });
      setSessionId(data.session_id);
      setParsedQuery(data.parsed_query);
      setDiscovery(data.discovery_products || []);
      setSelectedIds([]);
      setPriorities([]);
      setSelectedPlatforms(platforms.map((p) => p.id));
      setPincode("");
      setComparison(null);
      setStep("discover");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setLoadingLabel("");
    }
  }

  function toggleSelection(id) {
    setSelectedIds((current) => {
      if (current.includes(id)) return current.filter((x) => x !== id);
      if (current.length >= 5) return current; // Phase 2: cap raised 2 -> 5
      return [...current, id];
    });
  }

  function togglePriority(id) {
    setPriorities((current) => {
      if (current.includes(id)) return current.filter((x) => x !== id);
      if (current.length >= 3) return current; // Phase 2: 1-3 priorities
      return [...current, id];
    });
  }

  function togglePlatform(id) {
    setSelectedPlatforms((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
    );
  }

  async function handleCompare(event) {
    event?.preventDefault();
    if (
      selectedIds.length < 1 ||
      priorities.length < 1 ||
      selectedPlatforms.length < 1 ||
      pincode.trim().length < 4
    )
      return;
    setLoading(true);
    setLoadingLabel("Searching around your picks and comparing the market…");
    setError("");
    try {
      await api("/api/search/preferences", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          selected_product_ids: selectedIds,
          priorities,
          pincode: pincode.trim(),
          selected_platforms: selectedPlatforms,
        }),
      });
      const data = await api("/api/search/compare", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      });
      setComparison(data);
      setStep("compare");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
      setLoadingLabel("");
    }
  }

  function startOver() {
    setStep("search");
    setQuery("");
    setSessionId("");
    setParsedQuery(null);
    setDiscovery([]);
    setSelectedIds([]);
    setPriorities([]);
    setSelectedPlatforms(platforms.map((p) => p.id));
    setPincode("");
    setComparison(null);
    setError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="app-shell">
      <Header onLogo={startOver} step={step} />

      {error && (
        <div className="error-banner">
          <span>!</span>
          <div>{error}</div>
          <button onClick={() => setError("")}>×</button>
        </div>
      )}

      <main>
        {step === "search" && (
          <SearchView
            query={query}
            setQuery={setQuery}
            onSubmit={handleDiscover}
            loading={loading}
          />
        )}

        {step === "discover" && (
          <DiscoverView
            query={query}
            parsedQuery={parsedQuery}
            products={discovery}
            selectedIds={selectedIds}
            onToggle={toggleSelection}
            onContinue={() => setStep("preferences")}
            onBack={startOver}
            loading={loading}
          />
        )}

        {step === "preferences" && (
          <PreferencesView
            products={selectedProducts}
            priorities={priorities}
            onTogglePriority={togglePriority}
            platforms={platforms}
            platformsStatus={platformsStatus}
            onRetryPlatforms={loadPlatforms}
            selectedPlatforms={selectedPlatforms}
            onTogglePlatform={togglePlatform}
            pincode={pincode}
            setPincode={setPincode}
            onSubmit={handleCompare}
            onBack={() => setStep("discover")}
            loading={loading}
          />
        )}

        {step === "compare" && comparison && (
          <CompareView
            query={query}
            comparison={comparison}
            selectedProducts={selectedProducts}
            onBack={() => {
              setStep("preferences");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            onStartOver={startOver}
          />
        )}
      </main>

      {loading && <LoadingOverlay label={loadingLabel} />}
    </div>
  );
}

function Header({ onLogo, step }) {
  const labels = ["Discover", "Choose", "Compare"];
  const current = step === "search" ? 0 : step === "discover" ? 0 : step === "preferences" ? 1 : 2;

  return (
    <header className="topbar">
      <button className="brand" onClick={onLogo} aria-label="Findly home">
        <span className="brand-mark">F</span>
        <span>findly</span>
      </button>

      <div className="stepper">
        {labels.map((label, index) => (
          <React.Fragment key={label}>
            <div className={`step ${index <= current ? "active" : ""}`}>
              <span className="step-dot">{index < current ? "✓" : index + 1}</span>
              <span>{label}</span>
            </div>
            {index < labels.length - 1 && <div className={`step-line ${index < current ? "active" : ""}`} />}
          </React.Fragment>
        ))}
      </div>

      <div className="header-note">AI shopping companion</div>
    </header>
  );
}

function SearchView({ query, setQuery, onSubmit, loading }) {
  const examples = ["red dress for a wedding", "black sneakers under ₹3000", "minimal gold earrings"];

  return (
    <section className="hero">
      <div className="hero-orb orb-one" />
      <div className="hero-orb orb-two" />
      <div className="hero-content">
        <div className="eyebrow">SHOP WITH A LITTLE MORE CLARITY</div>
        <h1>Don’t search harder.<br /><em>Choose smarter.</em></h1>
        <p className="hero-copy">
          Tell us what you’re looking for. We’ll help you discover what you like,
          compare it across the market, and understand the trade-offs.
        </p>

        <form className="search-box" onSubmit={onSubmit}>
          <span className="search-icon">⌕</span>
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What are you shopping for?"
            disabled={loading}
          />
          <button type="submit" disabled={loading || query.trim().length < 2}>
            {loading ? "Finding…" : "Find for me"}
            <span>→</span>
          </button>
        </form>

        <div className="example-row">
          <span>Try:</span>
          {examples.map((example) => (
            <button key={example} onClick={() => setQuery(example)}>{example}</button>
          ))}
        </div>

        <div className="promise-row">
          <div><span>01</span><strong>Discover</strong><small>See a few styles, not hundreds.</small></div>
          <div><span>02</span><strong>Choose</strong><small>Tell us what catches your eye.</small></div>
          <div><span>03</span><strong>Compare</strong><small>See price, reviews & trade-offs.</small></div>
        </div>
      </div>
    </section>
  );
}

function QueryChips({ parsed }) {
  if (!parsed) return null;
  const chips = [
    parsed.category,
    parsed.subcategory,
    parsed.color,
    parsed.gender,
    parsed.occasion,
    ...(parsed.style_keywords || []),
  ].filter(Boolean);

  return (
    <div className="query-chips">
      {chips.slice(0, 6).map((chip, i) => <span key={`${chip}-${i}`}>{chip}</span>)}
      {(parsed.min_price || parsed.max_price) && (
        <span>
          {parsed.min_price ? `₹${parsed.min_price.toLocaleString("en-IN")}` : "₹0"} – {parsed.max_price ? `₹${parsed.max_price.toLocaleString("en-IN")}` : "any"}
        </span>
      )}
    </div>
  );
}

function DiscoverView({ query, parsedQuery, products, selectedIds, onToggle, onContinue, onBack }) {
  return (
    <section className="page">
      <div className="page-heading">
        <div>
          <button className="back-link" onClick={onBack}>← Start over</button>
          <div className="eyebrow">STEP 1 · DISCOVER</div>
          <h2>Here’s a starting point for <em>“{query}”</em></h2>
          <p>Don’t overthink it. Pick up to five styles that feel like you.</p>
          <QueryChips parsed={parsedQuery} />
        </div>
        <div className="result-count">{products.length} <span>styles</span></div>
      </div>

      <div className="discovery-grid">
        {products.map((product, index) => (
          <DiscoveryCard
            key={product.id}
            product={product}
            index={index}
            selected={selectedIds.includes(product.id)}
            disabled={!selectedIds.includes(product.id) && selectedIds.length >= 5}
            onClick={() => onToggle(product.id)}
          />
        ))}
      </div>

      <div className="sticky-action">
        <div>
          <strong>{selectedIds.length ? `${selectedIds.length} selected` : "Pick 1–5 favourites"}</strong>
          <span>We’ll search around your choices next.</span>
        </div>
        <button className="primary-btn" disabled={!selectedIds.length} onClick={onContinue}>
          Continue <span>→</span>
        </button>
      </div>
    </section>
  );
}

function DiscoveryCard({ product, index, selected, disabled, onClick }) {
  return (
    <button
      className={`discovery-card ${selected ? "selected" : ""} ${disabled ? "disabled" : ""}`}
      onClick={onClick}
      disabled={disabled}
    >
      <div className="card-image-wrap">
        {product.thumbnail_url ? (
          <img src={product.thumbnail_url} alt="" className="card-image" />
        ) : (
          <div className="image-placeholder">No image</div>
        )}
        <span className="card-number">0{index + 1}</span>
        {selected && <span className="selected-badge">✓</span>}
      </div>
      <div className="card-body">
        <div className="retailer">{product.source}</div>
        <h3>{product.title}</h3>
        <div className="card-meta">
          <strong>{formatPrice(product.price)}</strong>
          {product.rating != null && (
            <span className="rating"><span>★</span> {product.rating.toFixed(1)} {product.reviews_count ? `(${formatCount(product.reviews_count)})` : ""}</span>
          )}
        </div>
      </div>
    </button>
  );
}

function PreferencesView({
  products,
  priorities,
  onTogglePriority,
  platforms,
  platformsStatus,
  onRetryPlatforms,
  selectedPlatforms,
  onTogglePlatform,
  pincode,
  setPincode,
  onSubmit,
  onBack,
  loading,
}) {
  const canSubmit = priorities.length >= 1 && selectedPlatforms.length >= 1 && pincode.length >= 4 && !loading;

  return (
    <section className="page narrow-page">
      <button className="back-link" onClick={onBack}>← Back to styles</button>
      <div className="preference-heading">
        <div className="eyebrow">STEP 2 · TELL US WHAT MATTERS</div>
        <h2>Now let’s make this <em>personal.</em></h2>
        <p>You liked these. What should we optimise for when we search the wider market?</p>
      </div>

      <div className="selected-strip">
        {products.map((product) => (
          <div className="mini-product" key={product.id}>
            {product.thumbnail_url ? <img src={product.thumbnail_url} alt="" /> : <div className="mini-placeholder" />}
            <div><span>{product.source}</span><strong>{product.title}</strong></div>
          </div>
        ))}
      </div>

      <form onSubmit={onSubmit}>
        <div className="preference-block">
          <div className="block-label">
            <span>01</span>
            <div>
              <strong>What matters most?</strong>
              <small>Pick 1–3 — we’ll blend them together into one ranking.</small>
            </div>
          </div>
          <div className="priority-grid">
            {PRIORITIES.map((item) => {
              const selected = priorities.includes(item.id);
              const disabled = !selected && priorities.length >= 3;
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`priority-card ${selected ? "selected" : ""} ${disabled ? "disabled" : ""}`}
                  onClick={() => onTogglePriority(item.id)}
                  disabled={disabled}
                >
                  <span className="priority-icon">{item.icon}</span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                  {selected && <span className="priority-check">✓</span>}
                </button>
              );
            })}
          </div>
        </div>

        <div className="preference-block">
          <div className="block-label">
            <span>02</span>
            <div>
              <strong>Where should we look?</strong>
              <small>Pick at least one platform to search in the next step.</small>
            </div>
          </div>
          {platformsStatus === "loading" && <p className="delivery-note">Loading platforms…</p>}
          {platformsStatus === "error" && (
            <p className="delivery-note">
              Couldn’t load the platform list.{" "}
              <button type="button" className="back-link" onClick={onRetryPlatforms}>Try again</button>
            </p>
          )}
          {/* Reuses the priority-card/grid styling — there's no dedicated platform-pill CSS yet. */}
          {platformsStatus === "ready" && (
            <div className="priority-grid">
              {platforms.map((item) => {
                const selected = selectedPlatforms.includes(item.id);
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`priority-card ${selected ? "selected" : ""}`}
                    onClick={() => onTogglePlatform(item.id)}
                  >
                    <strong>{item.label}</strong>
                    {selected && <span className="priority-check">✓</span>}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="preference-block delivery-block">
          <div className="block-label"><span>03</span><div><strong>Where should we deliver?</strong><small>We’ll use your pincode to estimate delivery speed per product.</small></div></div>
          <div className="pincode-wrap">
            <span>⌖</span>
            <input
              inputMode="numeric"
              maxLength={6}
              value={pincode}
              onChange={(e) => setPincode(e.target.value.replace(/\D/g, ""))}
              placeholder="6-digit pincode"
              required
            />
            <span className="india-tag">INDIA</span>
          </div>
          <p className="delivery-note">Delivery shown in the results is a pincode + retailer-speed estimate, not a live retailer quote.</p>
        </div>

        <button className="primary-btn wide" disabled={!canSubmit}>
          {loading ? "Comparing…" : "Find my best options"} <span>→</span>
        </button>
        <button type="button" className="back-link" onClick={onBack}>← Back to styles</button>
      </form>
    </section>
  );
}

function CompareView({ query, comparison, selectedProducts, onBack, onStartOver }) {
  const products = comparison.compared_products || [];
  const pickIds = new Set(selectedProducts.map((p) => p.id));
  // Platforms the user asked for where the search found nothing usable.
  const emptyPlatforms = (comparison.platform_coverage || []).filter((c) => c.candidates_found === 0);

  return (
    <section className="page">
      <div className="comparison-header">
        <div>
          <button className="back-link" onClick={onBack}>← Change preferences</button>{" "}
          <button className="back-link" onClick={onStartOver}>New search</button>
          <div className="eyebrow">STEP 3 · YOUR SHORTLIST</div>
          <h2>Now you have <em>options worth considering.</em></h2>
          <p>{comparison.overall_summary}</p>
        </div>
        <div className="market-stat">
          <strong>{products.length}</strong>
          <span>options compared</span>
        </div>
      </div>

      <div className="selected-context">
        <div className="context-title">You liked</div>
        {selectedProducts.map((product) => (
          <div className="context-product" key={product.id}>
            {product.thumbnail_url ? <img src={product.thumbnail_url} alt="" /> : <div className="mini-placeholder" />}
            <span>{product.title}</span>
          </div>
        ))}
        <div className="context-priority">
          {(comparison.priorities || []).length > 1 ? "Priorities" : "Priority"}:{" "}
          <strong>
            {(comparison.priorities || [])
              .map((id) => PRIORITIES.find((p) => p.id === id)?.label || id)
              .join(" + ")}
          </strong>
        </div>
      </div>

      {emptyPlatforms.length > 0 && (
        <div className="bottom-note">
          <span>!</span>
          <div>
            <strong>No listings found on {emptyPlatforms.map((c) => c.label).join(", ")}.</strong>{" "}
            We search through Google Shopping, which doesn’t carry every retailer’s full catalogue.
            Products you picked yourself are still shown below.
          </div>
        </div>
      )}

      <div className="compare-grid">
        {products.map((product, index) => (
          <ComparisonCard
            key={product.id}
            product={product}
            index={index}
            featured={index === 0}
            isPick={pickIds.has(product.id)}
            priorities={comparison.priorities || []}
          />
        ))}
      </div>

      <div className="bottom-note">
        <span>✦</span>
        <div><strong>The point isn’t one “perfect” product.</strong> Compare the trade-offs and choose what fits this purchase best.</div>
      </div>
    </section>
  );
}

function ComparisonCard({ product, index, featured, isPick, priorities }) {
  const confidence = product.delivery_confidence;
  return (
    <article className={`comparison-card ${featured ? "featured" : ""}`}>
      <div className="comparison-image-wrap">
        {product.thumbnail_url ? <img src={product.thumbnail_url} alt="" /> : <div className="image-placeholder">No image</div>}
        {featured && <span className="match-pill">TOP MATCH</span>}
        <span className="rank-pill">#{index + 1}</span>
      </div>
      <div className="comparison-body">
        <div className="retailer">{product.source}{isPick && " · YOUR PICK"}</div>
        <h3>{product.title}</h3>

        <div className="price-row">
          <strong>{formatPrice(product.price)}</strong>
          {product.original_price && product.original_price > product.price && (
            <del>{formatPrice(product.original_price)}</del>
          )}
        </div>

        <div className="signal-row">
          {product.rating != null && <span className="signal rating"><b>★</b> {product.rating.toFixed(1)}</span>}
          {product.reviews_count != null && <span className="signal">{formatCount(product.reviews_count)} reviews</span>}
        </div>

        <MatchBars product={product} priorities={priorities} />

        {product.visual_similarity_score != null && (
          <div className="look-badge" title="How closely this listing's photo matches the product you picked">
            <span>◐</span> {Math.round(product.visual_similarity_score * 100)}% look-alike to your pick
          </div>
        )}

        {product.delivery_estimate ? (
          <div className={`delivery-pill ${confidence}`}>
            <span>⌁</span> {product.delivery_estimate}
            {confidence === "estimated" && <small>estimated</small>}
          </div>
        ) : (
          <div className="delivery-pill unknown"><span>⌁</span> Delivery info unavailable</div>
        )}

        {product.trade_off_note && (
          <div className="tradeoff">
            <span>✦</span>
            <p>{product.trade_off_note}</p>
          </div>
        )}

        {product.product_url && (
          <a className="retailer-btn" href={product.product_url} target="_blank" rel="noreferrer">
            View at {product.source} <span>↗</span>
          </a>
        )}
      </div>
    </article>
  );
}

// Phase 2 (Req 8): one bar per selected priority. The value is relative to the
// best option in THIS comparison (100% = best here), not an absolute grade.
function MatchBars({ product, priorities }) {
  const match = product.priority_match || {};
  const rows = priorities.filter((id) => match[id] !== undefined);
  if (rows.length === 0) return null;
  return (
    <div className="match-bars" aria-label="How well this product fits each of your priorities">
      {rows.map((id) => {
        const label = PRIORITIES.find((p) => p.id === id)?.label || id;
        const pct = Math.max(0, Math.min(100, Math.round(match[id])));
        return (
          <div className="match-row" key={id}>
            <div className="match-label"><span>{label}</span><b>{pct}%</b></div>
            <div className="match-track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className={`match-fill ${pct >= 75 ? "high" : pct >= 40 ? "mid" : "low"}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
      <small className="match-caption">vs. the best option in this list</small>
    </div>
  );
}

function LoadingOverlay({ label }) {
  return (
    <div className="loading-overlay">
      <div className="loader-card">
        <div className="loader-orbit"><span /></div>
        <strong>{label}</strong>
        <small>This can take up to a minute while we search each platform and check how products look.</small>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);