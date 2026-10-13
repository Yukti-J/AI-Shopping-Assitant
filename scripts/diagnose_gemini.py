"""
Finds WHY Gemini-powered features (query parsing, trade-off notes, color
validation, image matching) are not working. Prints the real error at each
layer instead of hiding it. Prints no secrets.

    python scripts/diagnose_gemini.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import google.generativeai as genai

from app.core.config import get_settings

s = get_settings()


def step(n, title):
    print(f"\n[{n}] {title}")


step(1, "Effective settings")
print("  GEMINI_MODEL        :", s.GEMINI_MODEL)
print("  vision model        :", s.gemini_vision_model)
print("  GEMINI key present  :", bool(s.GEMINI_API_KEY), f"(length {len(s.GEMINI_API_KEY)})")
print("  SERPAPI key present :", bool(s.SERPAPI_API_KEY), f"(length {len(s.SERPAPI_API_KEY)})")
for name in ("GEMINI_MODEL", "GEMINI_VISION_MODEL", "GEMINI_API_KEY"):
    if name in os.environ:
        print(f"  NOTE: Windows env var {name} is set and OVERRIDES .env")

genai.configure(api_key=s.GEMINI_API_KEY)

step(2, "Plain text call")
try:
    r = genai.GenerativeModel(s.GEMINI_MODEL).generate_content("Reply with the single word: ok")
    print("  OK  ->", r.text.strip()[:60])
except Exception as e:  # noqa: BLE001
    print("  FAILED ->", type(e).__name__, ":", str(e)[:400])
    print("  (Text calls fail, so the problem is model name / key / quota / network — not image code.)")

step(3, "Get two real product thumbnails from SerpAPI")
thumbs = []
try:
    resp = httpx.get("https://serpapi.com/search.json", timeout=30, params={
        "engine": "google_shopping", "q": "red dress for women", "gl": s.SERPAPI_COUNTRY,
        "hl": s.SERPAPI_LANGUAGE, "api_key": s.SERPAPI_API_KEY})
    resp.raise_for_status()
    thumbs = [x.get("thumbnail") for x in resp.json().get("shopping_results", []) if x.get("thumbnail")][:2]
    for t in thumbs:
        print("  thumbnail:", t[:90])
except Exception as e:  # noqa: BLE001
    print("  FAILED ->", type(e).__name__, ":", str(e)[:300])

step(4, "Download those thumbnails")
imgs = []
for t in thumbs:
    try:
        if t.startswith("data:"):
            import base64
            raw = base64.b64decode(t.split(",", 1)[1])
        else:
            rr = httpx.get(t, timeout=15, follow_redirects=True)
            rr.raise_for_status()
            raw = rr.content
        print(f"  OK  {len(raw)} bytes, starts {raw[:4]!r}")
        imgs.append(raw)
    except Exception as e:  # noqa: BLE001
        print("  FAILED ->", type(e).__name__, ":", str(e)[:300])

step(5, "Vision call with both images (same call image matching makes)")
if len(imgs) == 2:
    from app.services.image_matching import _PROMPT, _sniff_mime
    try:
        m = genai.GenerativeModel(s.gemini_vision_model)
        r = m.generate_content(
            [_PROMPT, "Image 1:", {"mime_type": _sniff_mime(imgs[0]), "data": imgs[0]},
             "Image 2:", {"mime_type": _sniff_mime(imgs[1]), "data": imgs[1]}],
            generation_config={"temperature": 0})
        print("  OK  ->", r.text.strip()[:200])
    except Exception as e:  # noqa: BLE001
        print("  FAILED ->", type(e).__name__, ":", str(e)[:500])
else:
    print("  skipped (need 2 downloaded images)")

step(6, "App's own parse_query")
try:
    from app.services.gemini_service import GeminiService
    print("  ", GeminiService().parse_query("red dress for women"))
except Exception as e:  # noqa: BLE001
    print("  FAILED ->", type(e).__name__, ":", str(e)[:300])

print("\nDone. Paste everything above (it contains no keys) back to Claude.")