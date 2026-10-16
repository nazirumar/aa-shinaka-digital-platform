"""Image acquisition for the development seeder.

The seeder needs real, valid image files so that ``ImageField`` records render
in the browser. Two sources are used, in order:

1. **Wikipedia / Wikimedia Commons** lead images fetched through the public
   MediaWiki ``pageimages`` API (thematically relevant and openly licensed).
2. **picsum.photos** seeded placeholders as a deterministic fallback whenever a
   topic has no mapped article or the network call fails.

Every downloaded/fabricated image is normalised with Pillow (RGB, resized,
re-encoded as JPEG) so the stored files always satisfy the catalogue upload
validators (extension + 5 MB size) and look consistent.

This module is development-only tooling. It never runs in production and never
writes secrets or user data.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request

from django.core.files.base import ContentFile
from PIL import Image, ImageDraw, ImageFont

USER_AGENT = "AAShinakaSeed/1.0 (development seeder; +https://example.invalid)"
WIKI_API = "https://en.wikipedia.org/w/api.php"
PICSUM_URL = "https://picsum.photos/seed/{seed}/{width}/{height}"
PICSUM_GRAYSCALE_URL = "https://picsum.photos/seed/{seed}/{width}/{height}?grayscale"
TIMEOUT_SECONDS = 30

# Default output geometry (kept well within the 5 MB / 5 MP validators).
DEFAULT_SIZE = (1600, 1200)
DEFAULT_QUALITY = 82

#: Topic key -> Wikipedia article title whose lead image is thematically right.
#: Topics that are absent here fall back to a deterministic picsum image.
WIKI_TOPICS: dict[str, str] = {
    # Produce / catalogue
    "maize": "Maize",
    "rice": "Rice",
    "sorghum": "Sorghum",
    "millet": "Pearl millet",
    "cowpea": "Cowpea",
    "groundnut": "Peanut",
    "soybean": "Soybean",
    "sesame": "Sesame",
    "cassava": "Cassava",
    "yam": "Yam (vegetable)",
    "sweet_potato": "Sweet potato",
    "irish_potato": "Potato",
    "tomato": "Tomato",
    "onion": "Onion",
    "pepper": "Chili pepper",
    "okra": "Okra",
    "plantain": "Cooking banana",
    "orange": "Orange (fruit)",
    "mango": "Mango",
    "pineapple": "Pineapple",
    "watermelon": "Watermelon",
    "cocoa": "Cocoa bean",
    "cashew": "Cashew",
    "ginger": "Ginger",
    "palm_oil": "Palm oil",
    "eggs": "Chicken egg",
    "poultry": "Broiler",
    "goat": "Goat",
    "fertiliser": "Fertilizer",
    "seeds": "Seed",
    # Site / marketing / operations
    "farm": "Agriculture",
    "farmland": "Farm",
    "tractor": "Tractor",
    "greenhouse": "Greenhouse",
    "irrigation": "Irrigation",
    "warehouse": "Warehouse",
    "storage": "Grain storage",
    "market": "Market (place)",
    "marketplace": "Farmers' market",
    "training": "Classroom",
    "classroom": "Lecture",
    "consultation": "Meeting",
    "handshake": "Handshake",
    "logistics": "Logistics",
    "port": "Port",
    "shipping": "Container ship",
    "airfreight": "Cargo aircraft",
    "quality": "Quality control",
    "laboratory": "Laboratory",
    "packaging": "Packaging and labeling",
    "solar": "Solar panel",
    "team": "Businessperson",
    "portrait_woman": "Portrait",
    "portrait_man": "Portrait",
    "sustainability": "Sustainable agriculture",
    "finance": "Accounting",
    "technology": "Agriculture 4.0",
    "harvest": "Harvest",
    "livestock": "Livestock",
    "agroforestry": "Agroforestry",
    "cooperative": "Cooperative",
    "seedling": "Seedling",
}


def _humanize(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().title() or "AA Shinaka"


def _load_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - older Pillow
        return ImageFont.load_default()


def _normalise(raw: bytes, *, size=DEFAULT_SIZE, quality: int = DEFAULT_QUALITY) -> bytes:
    """Decode arbitrary image bytes and return a clean RGB JPEG."""
    image = Image.open(io.BytesIO(raw))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    image.thumbnail(size)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _gradient_placeholder(label: str, *, size=DEFAULT_SIZE, palette=None) -> bytes:
    width, height = size
    top, bottom = palette or ((21, 94, 63), (12, 43, 31))  # deep greens
    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        colour = tuple(round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=colour)
    text = _humanize(label)
    font = _load_font(max(28, width // 14))
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - text_width) / 2, (height - text_height) / 2),
        text,
        fill=(245, 250, 245),
        font=font,
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue()


def _http_get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.read()


def _wiki_image_bytes(title: str) -> bytes:
    query = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "pageimages",
            "pithumbsize": 1600,
            "redirects": 1,
            "titles": title,
        }
    )
    payload = json.loads(_http_get(f"{WIKI_API}?{query}").decode("utf-8"))
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        thumbnail = page.get("thumbnail") or {}
        source = thumbnail.get("source")
        if source:
            return _http_get(source)
    raise LookupError(f"No lead image for Wikipedia article {title!r}")


class ImageLibrary:
    """Fetches, normalises and caches seed images as :class:`ContentFile` bytes.

    Calling :meth:`get` twice with the same key returns fresh ``ContentFile``
    objects backed by a single in-memory download.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        size=DEFAULT_SIZE,
        quality: int = DEFAULT_QUALITY,
        verbosity: int = 1,
        logger=None,
    ) -> None:
        self.enabled = enabled
        self.size = size
        self.quality = quality
        self.verbosity = verbosity
        self.logger = logger
        self._cache: dict[str, bytes] = {}
        self.sources: dict[str, str] = {}

    # -- public API ---------------------------------------------------------

    def image(self, key: str, *, filename: str | None = None) -> ContentFile:
        """Return a ``ContentFile`` for ``key`` (download once, reuse bytes)."""
        filename = filename or f"{key}.jpg"
        if not filename.lower().endswith(".jpg"):
            filename = f"{filename.rsplit('.', 1)[0]}.jpg"
        return ContentFile(self._bytes(key), name=filename)

    def made(self, key: str) -> str:
        return self.sources.get(key, "unknown")

    def logo(self, *, name: str = "AA Shinaka Logo") -> ContentFile:
        width, height = 900, 260
        image = Image.new("RGB", (width, height), (20, 83, 45))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (18, 18, width - 18, height - 18),
            radius=28,
            outline=(202, 226, 202),
            width=4,
        )
        # A simple leaf mark.
        draw.ellipse((52, 70, 132, 190), fill=(134, 197, 105))
        draw.polygon([(64, 130), (176, 60), (150, 190)], fill=(74, 148, 70))
        title = name.replace(" Logo", "").upper()
        font = _load_font(84)
        draw.text((190, 92), title, fill=(245, 250, 245), font=font)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return ContentFile(buffer.getvalue(), name="aa-shinaka-logo.png")

    def favicon(self) -> ContentFile:
        size = 128
        image = Image.new("RGB", (size, size), (20, 83, 45))
        draw = ImageDraw.Draw(image)
        draw.ellipse((24, 24, size - 24, size - 24), fill=(134, 197, 105))
        draw.polygon(
            [(30, 66), (98, 30), (86, 104)],
            fill=(74, 148, 70),
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return ContentFile(buffer.getvalue(), name="aa-shinaka-favicon.png")

    # -- internals ----------------------------------------------------------

    def _bytes(self, key: str) -> bytes:
        if key in self._cache:
            return self._cache[key]

        raw: bytes | None = None
        source = "placeholder"

        if self.enabled:
            title = WIKI_TOPICS.get(key)
            if title:
                try:
                    raw = _wiki_image_bytes(title)
                    source = f"wikipedia:{title}"
                except (urllib.error.URLError, LookupError, ValueError, OSError) as exc:
                    self._log(f"    ! wikipedia image for '{key}' failed: {exc}")
            if raw is None:
                try:
                    raw = _http_get(
                        PICSUM_URL.format(seed=urllib.parse.quote(key), width=1600, height=1200)
                    )
                    source = "picsum"
                except (urllib.error.URLError, OSError) as exc:
                    self._log(f"    ! picsum image for '{key}' failed: {exc}")

        if raw is None:
            raw = _gradient_placeholder(key, size=self.size)
        else:
            try:
                raw = _normalise(raw, size=self.size, quality=self.quality)
            except OSError as exc:
                self._log(f"    ! image decode for '{key}' failed: {exc}; using placeholder")
                raw = _gradient_placeholder(key, size=self.size)
                source = "placeholder"

        self._cache[key] = raw
        self.sources[key] = source
        self._log(f"    · image '{key}' ← {source} ({len(raw) // 1024} KB)")
        return raw

    def _log(self, message: str) -> None:
        if self.logger and self.verbosity >= 2:
            self.logger(message)
