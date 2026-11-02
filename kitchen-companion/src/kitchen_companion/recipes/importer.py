"""Import a recipe from a web page's schema.org Recipe JSON-LD.

The server fetches URLs that users paste, so every hop goes through an SSRF guard: http(s) only,
and every address the host resolves to must be public. Redirects are followed by hand so each
one is checked too.
"""

import asyncio
import hashlib
import html
import ipaddress
import json
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from kitchen_companion.recipes.ingredients import parse_ingredient
from kitchen_companion.recipes.model import Recipe, Step

TIMEOUT_S = 10.0
MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 3
DEFAULT_SERVINGS = 4
NOT_FOUND = "Couldn't find a recipe on that page."


class RecipeNotFound(ValueError):
    pass


class ImportBlocked(ValueError):
    pass


# -- pure parsing --------------------------------------------------------------------------------

_ISO = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$", re.IGNORECASE)
_HINT = re.compile(
    r"(\d+)(?:\s*(?:-|–|—|to)\s*\d+)?\s*(minutes?|mins?|min|hours?|hrs?)\b", re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")


def parse_iso_minutes(s: str | None) -> int | None:
    if not s or not isinstance(s, str):
        return None
    m = _ISO.match(s.strip())
    if not m or not any(m.groups()):
        return None
    days, hours, minutes, _ = (int(float(g)) if g else 0 for g in m.groups())
    return days * 1440 + hours * 60 + minutes


def timer_hint(step_text: str) -> int | None:
    m = _HINT.search(step_text)
    if not m:
        return None
    value = int(m.group(1))
    return value * 60 if m.group(2).lower().startswith("h") else value


class _LdJsonCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            kind = (dict(attrs).get("type") or "").split(";")[0].strip().lower()
            self._in_ld = kind == "application/ld+json"
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.blocks.append("".join(self._buf))
            self._in_ld = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)


def _is_recipe(node: dict) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.split("/")[-1] == "Recipe" for k in kinds)


def _find_recipe(node: object, depth: int = 0) -> dict | None:
    if depth > 8:
        return None
    if isinstance(node, list):
        for item in node:
            found = _find_recipe(item, depth + 1)
            if found:
                return found
    elif isinstance(node, dict):
        if _is_recipe(node):
            return node
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if key in node:
                found = _find_recipe(node[key], depth + 1)
                if found:
                    return found
    return None


def _clean(text: object) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


def _instruction_texts(node: object) -> list[str]:
    if isinstance(node, str):
        lines = [_clean(line) for line in re.split(r"\r?\n+", html.unescape(node))]
        return [line for line in lines if line]
    if isinstance(node, list):
        return [text for item in node for text in _instruction_texts(item)]
    if isinstance(node, dict):
        if "itemListElement" in node:
            return _instruction_texts(node["itemListElement"])
        text = _clean(node.get("text") or node.get("name"))
        return [text] if text else []
    return []


def _servings(value: object) -> int:
    values = value if isinstance(value, list) else [value]
    for v in values:
        if isinstance(v, int | float) and v > 0:
            return int(v)
        m = re.search(r"\d+", str(v or ""))
        if m and int(m.group()) > 0:
            return int(m.group())
    return DEFAULT_SERVINGS


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "recipe"


def extract_recipe(html_text: str, source_url: str) -> Recipe:
    collector = _LdJsonCollector()
    collector.feed(html_text)
    node = None
    for block in collector.blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        node = _find_recipe(data)
        if node:
            break
    if node is None:
        raise RecipeNotFound(NOT_FOUND)

    title = _clean(node.get("name")) or "Imported recipe"
    lines = node.get("recipeIngredient") or node.get("ingredients") or []
    if isinstance(lines, str):
        lines = [lines]
    texts = _instruction_texts(node.get("recipeInstructions"))
    total = parse_iso_minutes(node.get("totalTime"))
    if total is None:
        parts = [parse_iso_minutes(node.get(k)) for k in ("prepTime", "cookTime")]
        total = sum(p for p in parts if p) or None
    return Recipe(
        id=f"{_slugify(title)}-{hashlib.sha1(source_url.encode()).hexdigest()[:6]}",
        title=title,
        servings=_servings(node.get("recipeYield")),
        total_time_min=total,
        source_url=source_url,
        ingredients=[parse_ingredient(_clean(line)) for line in lines if _clean(line)],
        steps=[Step(index=i, text=t, timer_minutes=timer_hint(t)) for i, t in enumerate(texts)],
    )


# -- fetching ------------------------------------------------------------------------------------


def default_resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return []
    return sorted({info[4][0] for info in infos})


def _blocked(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return True
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified or not ip.is_global
    )


async def _check_url(url: str, resolve: Callable[[str], list[str]]) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ImportBlocked("Only http and https recipe links are allowed.")
    host = parts.hostname
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = await asyncio.to_thread(resolve, host)
    if not addresses:
        raise RecipeNotFound("Couldn't reach that page.")
    if any(_blocked(a) for a in addresses):
        raise ImportBlocked("That address isn't allowed.")


async def _fetch(url: str, transport, resolve) -> tuple[str, str]:
    headers = {"User-Agent": "KitchenCompanion/0.1 (recipe import)", "Accept": "text/html,*/*;q=0.8"}
    async with httpx.AsyncClient(transport=transport, follow_redirects=False, timeout=TIMEOUT_S,
                                 headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _check_url(url, resolve)
            async with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise RecipeNotFound(NOT_FOUND)
                    url = urljoin(url, location)
                    continue
                if resp.status_code != 200:
                    raise RecipeNotFound(NOT_FOUND)
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise RecipeNotFound("Couldn't import that: the page is too large.")
                return body.decode(resp.encoding or "utf-8", errors="replace"), url
    raise RecipeNotFound("Couldn't import that: too many redirects.")


async def import_recipe(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolve: Callable[[str], list[str]] = default_resolve,
) -> Recipe:
    try:
        async with asyncio.timeout(TIMEOUT_S):
            text, final_url = await _fetch(url.strip(), transport, resolve)
    except TimeoutError as e:
        raise RecipeNotFound("That page took too long to load.") from e
    except httpx.HTTPError as e:
        raise RecipeNotFound("Couldn't reach that page.") from e
    return extract_recipe(text, final_url)
