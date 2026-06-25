"""Site-specific knowledge — the ONE volatile module (spec §7.3 / NFR-1).

Every selector, endpoint, GraphQL query, enum literal, field path, page-size cap, and
cursor detail lives here and nowhere else. When Change.org changes, this is the only
file that should need editing. All values were verified against the live site by
reconnaissance and are kept honest by the live contract tests in tests/contract/.

The module exposes:
  * constants (endpoints, headers, page-size cap),
  * query builders (return GraphQL request bodies), and
  * pure parse functions (raw GraphQL dict -> flat field dict), which raise
    AdapterParseError on shape drift so callers can fail loud (FR-7.4).
"""

from __future__ import annotations

from typing import Any

# Bump when any value in this module changes (recorded on every Run; spec 6.5).
ADAPTER_VERSION = "changeorg-corgi-5.2153.0"

BASE_URL = "https://www.change.org"
GRAPHQL_URL = f"{BASE_URL}/api-proxy/graphql"
CSRF_URL = f"{BASE_URL}/api-proxy/-/csrf-token"
SITEMAP_INDEX_URL = f"{BASE_URL}/sitemap.xml"

# The api-proxy "client allowlist" is this single header value (app-name:version).
X_REQUESTED_WITH = "corgi-front-end-browser:5.2153.0"

# The comments connection ignores `first` beyond this; pagination is mandatory.
COMMENT_PAGE_SIZE = 20

# Valid inline enum literals (variable-typed enums are rejected by the schema).
# Inlined directly into the GraphQL below; kept here as the documented source of truth.
_COMMENT_SORT = "POPULAR"
_COMMENT_ROLES = "[SUPPORTER_COMMENT]"


class AdapterParseError(Exception):
    """Raised when a payload does not match the expected shape (markup drift)."""


def petition_url(slug: str) -> str:
    """Canonical petition URL for a slug."""
    return f"{BASE_URL}/p/{slug}"


# --------------------------------------------------------------------------- #
# Query builders
# --------------------------------------------------------------------------- #

_PETITION_QUERY = """
query PetitionMetadata($s: String!) {
  petition: petitionBySlugOrId(slugOrId: $s) {
    id
    slug
    ask
    displayTitle
    description
    createdAt
    publishedAt
    status
    isVerifiedVictory
    relevantLocationLocalizedName
    user { id displayName }
    organization { id name }
    signatureState {
      signatureCount { total displayed displayedLocalized }
      signatureGoal { displayed }
    }
    tagsConnection { nodes { id name slug } }
    commentsConnection(first: 1, sortBy: POPULAR, roles: [SUPPORTER_COMMENT]) {
      totalCount
    }
  }
}
"""


def petition_query(slug_or_id: str) -> dict[str, Any]:
    """GraphQL body fetching all petition metadata fields (spec §6.1)."""
    return {
        "operationName": "PetitionMetadata",
        "variables": {"s": slug_or_id},
        "query": _PETITION_QUERY,
    }


def comments_query(slug_or_id: str, after: str | None) -> dict[str, Any]:
    """GraphQL body for one comment page; `after` is an opaque cursor or None.

    Enum args and the cursor are inlined as literals (variable-typed enums are rejected,
    and the cursor's input type is ID). The slug stays a variable.
    """
    after_arg = f', after: "{after}"' if after else ""
    comments_args = (
        f"first: {COMMENT_PAGE_SIZE}, sortBy: {_COMMENT_SORT}, "
        f"roles: {_COMMENT_ROLES}{after_arg}"
    )
    query = (
        "query CommentPage($s: String!) {\n"
        "  petition: petitionBySlugOrId(slugOrId: $s) {\n"
        "    id\n"
        f"    commentsConnection({comments_args}) {{\n"
        "      totalCount\n"
        "      pageInfo { hasNextPage endCursor }\n"
        "      nodes {\n"
        "        id\n"
        "        comment\n"
        "        role\n"
        "        likes\n"
        "        createdAt\n"
        "        user { id displayName city }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    return {
        "operationName": "CommentPage",
        "variables": {"s": slug_or_id},
        "query": query,
    }


# NOTE on search discovery: Change.org's on-site search is an Algolia InstantSearch
# integration whose credentials are injected at runtime and whose result requests are
# gated by PerimeterX bot protection — it is not reachable from an automated client
# (verified by reconnaissance). There is therefore no GraphQL search operation to expose
# here. Keyword discovery is implemented over the sitemap in discovery.py, which
# remains the primary, exhaustive discovery channel.


# --------------------------------------------------------------------------- #
# Parse functions (raw GraphQL dict -> flat field dict). Pure; no I/O.
# --------------------------------------------------------------------------- #


def _require(data: dict[str, Any], *path: str) -> Any:
    """Walk a dict path, raising AdapterParseError if any key is missing."""
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise AdapterParseError(f"missing field path: {'.'.join(path)}")
        cur = cur[key]
    return cur


def parse_petition(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a PetitionMetadata response to flat petition fields (spec §6.1).

    Returns a dict with raw values; normalization to the model happens in normalize.py.
    Raises AdapterParseError if the core shape is absent.
    """
    p = _require(payload, "data", "petition")
    if p is None:
        raise AdapterParseError("petition not found (null)")
    sig = p.get("signatureState") or {}
    count = sig.get("signatureCount") or {}
    goal = sig.get("signatureGoal") or {}
    tags = (p.get("tagsConnection") or {}).get("nodes") or []
    return {
        "petition_id": _require(p, "id"),
        "slug": _require(p, "slug"),
        "url": petition_url(p["slug"]),
        "title": p.get("ask") or p.get("displayTitle"),
        "description": p.get("description"),
        "signatures_total": count.get("total"),
        "signatures_displayed": count.get("displayed"),
        "signatures_displayed_localized": count.get("displayedLocalized"),
        "goal": goal.get("displayed"),
        "created_at": p.get("createdAt"),
        "status": p.get("status"),
        "creator_name": (p.get("user") or {}).get("displayName"),
        "creator_location": p.get("relevantLocationLocalizedName"),
        "organization": (p.get("organization") or {}).get("name"),
        "is_verified_victory": p.get("isVerifiedVictory"),
        "comment_total": _require(p, "commentsConnection", "totalCount"),
        "tags": [
            {"tag_id": t["id"], "name": t.get("name"), "slug": t.get("slug")}
            for t in tags
            if t.get("id")
        ],
    }


def parse_comment_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a CommentPage response to {total, has_next, end_cursor, comments}."""
    conn = _require(payload, "data", "petition", "commentsConnection")
    page_info = conn.get("pageInfo") or {}
    nodes = conn.get("nodes") or []
    comments = []
    for n in nodes:
        if not n.get("id"):
            raise AdapterParseError("comment node missing id")
        user = n.get("user") or {}
        comments.append(
            {
                "comment_id": n["id"],
                "text": n.get("comment"),
                "role": n.get("role"),
                "likes": n.get("likes"),
                "city": user.get("city"),
                "created_at": n.get("createdAt"),
            }
        )
    return {
        "total": _require(conn, "totalCount"),
        "has_next": bool(page_info.get("hasNextPage")),
        "end_cursor": page_info.get("endCursor"),
        "comments": comments,
    }
