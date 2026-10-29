"""Data Explorer — MCP server for Week 5.

Wraps an open country dataset and exposes it to an agent as two MCP tools over STDIO:
`search_countries` (find countries by name) and `get_country_details` (currencies,
languages, borders, and flag URL for one country).

Data source: the open `mledoze/countries` dataset (the data REST Countries was built
on), served as one JSON file from GitHub. No API key. It is fetched over HTTPS on the
first successful call and cached in memory; a failed fetch is not cached, so the next
call retries.

Every tool returns structured data. Failures never raise: they come back as
`{"error": <message>, "error_type": <stable code>}` so the model can tell bad input,
upstream problems, and missing countries apart.

Setup:
    pip install -r requirements.txt
Run (STDIO) — register this command in your MCP client (e.g. Gemini CLI / Claude Desktop):
    python server.py
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

# Overridable so the error paths can be exercised from a real MCP client (see README).
DATA_URL = os.environ.get(
    "COUNTRIES_DATA_URL",
    "https://raw.githubusercontent.com/mledoze/countries/master/countries.json",
)
# Each country has a 3-letter `cca3` code; its flag lives at this URL. The files are
# named in lowercase (data/deu.svg), so the upper-case code must be lowered first.
FLAG_URL = "https://raw.githubusercontent.com/mledoze/countries/master/data/{cca3}.svg"
TIMEOUT_SECONDS = 10.0
MAX_QUERY_LENGTH = 100
MAX_LIMIT = 50
MAX_CANDIDATES = 10  # keep "ambiguous" errors small; the model can narrow the name

mcp = FastMCP("data-explorer")

_countries: list[dict] | None = None  # in-memory cache of the dataset


class DataUnavailable(Exception):
    """The dataset could not be fetched or parsed. `error_type` is a stable code."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def error(error_type: str, message: str, **extra) -> dict:
    """Build the structured error every tool returns instead of raising."""
    return {"error": message, "error_type": error_type, **extra}


def load_countries() -> list[dict]:
    """Download the dataset once and cache it. Raises DataUnavailable on any failure."""
    global _countries
    if _countries is not None:
        return _countries
    try:
        resp = httpx.get(DATA_URL, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        raise DataUnavailable(
            "upstream_timeout",
            f"The country dataset did not respond within {TIMEOUT_SECONDS:g} seconds. Try again later.",
        ) from None
    except httpx.HTTPStatusError as exc:
        raise DataUnavailable(
            "upstream_http_error",
            f"The country dataset returned HTTP {exc.response.status_code}. Try again later.",
        ) from None
    except httpx.HTTPError as exc:
        raise DataUnavailable(
            "upstream_unavailable",
            f"Could not reach the country dataset ({type(exc).__name__}). Try again later.",
        ) from None
    except ValueError:
        raise DataUnavailable(
            "bad_upstream_data", "The country dataset response was not valid JSON."
        ) from None
    if not isinstance(data, list) or not all(isinstance(c, dict) for c in data):
        raise DataUnavailable(
            "bad_upstream_data", "The country dataset had an unexpected format."
        )
    _countries = data
    return _countries


def clean_text(value, field: str) -> tuple[str | None, dict | None]:
    """Validate a free-text argument. Returns (stripped value, None) or (None, error)."""
    if not isinstance(value, str) or not value.strip():
        return None, error("invalid_input", f"{field} must be a non-empty string.")
    value = value.strip()
    if len(value) > MAX_QUERY_LENGTH:
        return None, error(
            "invalid_input", f"{field} must be at most {MAX_QUERY_LENGTH} characters."
        )
    return value, None


def common_name(country: dict) -> str:
    return (country.get("name") or {}).get("common") or country.get("cca3") or "?"


def official_name(country: dict) -> str:
    return (country.get("name") or {}).get("official") or ""


def searchable_names(country: dict) -> list[str]:
    """Lower-cased common name, official name, and alternative spellings."""
    names = [common_name(country), official_name(country)]
    names += [s for s in country.get("altSpellings") or [] if isinstance(s, str)]
    return [n.lower() for n in names if n]


@mcp.tool()
def search_countries(query: str, limit: int = 5) -> list[dict]:
    """Search countries by name (case-insensitive substring of the common name, official
    name, or an alternative spelling such as "Republic of Turkey").

    Returns up to `limit` (1-50) results as {name, capital, region, subregion}. An empty
    list means no country matched. On bad input or a data-source failure, returns a
    single-item list [{"error": ..., "error_type": ...}].
    """
    q, problem = clean_text(query, "query")
    if problem:
        return [problem]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        return [error("invalid_input", f"limit must be an integer from 1 to {MAX_LIMIT}.")]
    try:
        countries = load_countries()
    except DataUnavailable as exc:
        return [error(exc.error_type, exc.message)]

    q = q.lower()
    matches = [c for c in countries if any(q in n for n in searchable_names(c))]
    # No matches is not an error: return an empty list.
    results = []
    for c in matches[:limit]:
        results.append(
            {
                "name": common_name(c),
                "capital": (c.get("capital") or [None])[0],
                "region": c.get("region"),
                "subregion": c.get("subregion"),
            }
        )
    return results


def find_country(countries: list[dict], name: str) -> tuple[dict | None, dict | None]:
    """Resolve `name` to one country. Exact matches win over partial ones.

    Exact: common name, official name, 2- or 3-letter code, or an alternative spelling.
    Partial: substring of any of those names, used only if nothing is exact.
    Returns (country, None) or (None, error) for "not_found" / "ambiguous".
    """
    key = name.lower()

    def exact_keys(c: dict) -> set[str]:
        keys = {common_name(c), official_name(c), c.get("cca2") or "", c.get("cca3") or ""}
        keys.update(s for s in c.get("altSpellings") or [] if isinstance(s, str))
        return {k.lower() for k in keys if k}

    candidates = [c for c in countries if key in exact_keys(c)]
    if not candidates:
        candidates = [c for c in countries if any(key in n for n in searchable_names(c))]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, error(
            "not_found",
            f"No country matches '{name}'. Use search_countries to find the right name.",
        )
    names = sorted(common_name(c) for c in candidates)
    shown = names[:MAX_CANDIDATES]
    more = f" (showing {len(shown)})" if len(names) > len(shown) else ""
    return None, error(
        "ambiguous",
        f"'{name}' matches {len(names)} countries{more}. Call again with a more specific name.",
        candidates=shown,
        match_count=len(names),
    )


@mcp.tool()
def get_country_details(name: str) -> dict:
    """Get currencies, languages, bordering countries, and the flag URL for one country.

    `name` can be the common or official name ("Germany", "Federal Republic of
    Germany"), a 2- or 3-letter code ("DE", "DEU"), or an unambiguous part of a name.
    Exact matches win, so "Niger" returns Niger, not Nigeria.

    Returns {name, official_name, cca3, currencies: [{code, name, symbol}],
    languages: [str], borders: [{code, name}], flag_url}. Lists are empty when a country
    has none (e.g. island nations have no borders). On failure returns
    {"error": ..., "error_type": ...}; error_type is one of invalid_input, not_found,
    ambiguous (with "candidates" and "match_count"), upstream_timeout, upstream_http_error,
    upstream_unavailable, bad_upstream_data.
    """
    clean_name, problem = clean_text(name, "name")
    if problem:
        return problem
    try:
        countries = load_countries()
    except DataUnavailable as exc:
        return error(exc.error_type, exc.message)

    country, problem = find_country(countries, clean_name)
    if problem:
        return problem

    by_code = {c.get("cca3"): common_name(c) for c in countries if c.get("cca3")}
    currencies = [
        {"code": code, "name": (info or {}).get("name"), "symbol": (info or {}).get("symbol")}
        for code, info in (country.get("currencies") or {}).items()
    ]
    cca3 = country.get("cca3")
    return {
        "name": common_name(country),
        "official_name": official_name(country),
        "cca3": cca3,
        "currencies": currencies,
        "languages": sorted((country.get("languages") or {}).values()),
        "borders": [
            {"code": code, "name": by_code.get(code, code)}
            for code in country.get("borders") or []
        ],
        "flag_url": FLAG_URL.format(cca3=cca3.lower()) if cca3 else None,
    }


if __name__ == "__main__":
    mcp.run()
