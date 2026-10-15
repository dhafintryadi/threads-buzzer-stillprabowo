"""Parser generik untuk response GraphQL Threads."""

from __future__ import annotations

import json
import re
from typing import Any, Iterator, Optional

import config

_MEDIA_ABSENT_TYPE = 19


def is_feed_list_payload(payload: dict) -> bool:
    """True hanya untuk respons daftar aktivitas profil, bukan metrik post."""
    try:
        return isinstance(payload["data"]["mediaData"]["edges"], list)
    except (KeyError, TypeError):
        return False


def is_thread_reply_payload(payload: dict) -> bool:
    """True untuk respons halaman satu-post-dengan-balasan (threads.net/@user/post/kode)."""
    try:
        return isinstance(payload["data"]["data"]["edges"], list)
    except (KeyError, TypeError):
        return False


def iter_feed_thread_item_posts(payload: dict) -> Iterator[dict]:
    """Yield hanya post primer pada ``mediaData.edges[].thread_items``."""
    if not is_feed_list_payload(payload):
        return
    for edge in payload["data"]["mediaData"]["edges"]:
        node = edge.get("node") if isinstance(edge, dict) else None
        items = node.get("thread_items") if isinstance(node, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            post = item.get("post") if isinstance(item, dict) else None
            if isinstance(post, dict):
                yield post


def post_belongs_to_user(post: dict, target_user_id: str) -> bool:
    """Validasi bahwa item feed adalah aktivitas akun yang sedang dipindai."""
    user = post.get("user") or {}
    actual_id = user.get("pk") or user.get("id")
    return actual_id is not None and str(actual_id) == str(target_user_id)


def select_tab_posts(payload: dict, tab_name: str, user_id: str) -> list[dict]:
    """Tentukan post mana dari payload yang relevan untuk tab_name tertentu."""
    posts = list(iter_feed_thread_item_posts(payload))
    if tab_name == "reposts":
        return posts
    return [post for post in posts if post_belongs_to_user(post, user_id)]


def is_pinned_post(post: dict) -> bool:
    """True kalau post ini di-pin pemiliknya (``pinned_post_info`` non-null)."""
    tpi = post.get("text_post_app_info") or {}
    return bool(tpi.get("pinned_post_info"))


def reposted_post_pk(post: dict) -> Optional[str]:
    """Ambil penanda repost dari bentuk payload yang telah/berpotensi dipakai API."""
    tpi = post.get("text_post_app_info") or {}
    candidates = (
        (post.get("share_info") or {}).get("reposted_post"),
        (tpi.get("share_info") or {}).get("reposted_post"),
        tpi.get("reposted_post"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("pk") is not None:
            return str(candidate["pk"])
    return None


def walk_post_items(node: Any) -> Iterator[dict]:
    """Telusuri struktur JSON secara rekursif, hasilkan setiap dict yang "berbentuk" seperti objek post Threads (punya
    `pk` dan `taken_at`)."""
    if isinstance(node, dict):
        if "pk" in node and "taken_at" in node and isinstance(node.get("taken_at"), int):
            yield node
        for value in node.values():
            yield from walk_post_items(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_post_items(item)


def find_page_info(node: Any) -> Optional[dict]:
    """Cari dict `page_info` (berisi has_next_page/end_cursor) di mana pun posisinya dalam response."""
    if isinstance(node, dict):
        if "has_next_page" in node and "end_cursor" in node:
            return node
        for value in node.values():
            found = find_page_info(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_page_info(item)
            if found is not None:
                return found
    return None


def looks_like_user_profile_payload(payload: dict) -> bool:
    """Heuristik: response ini kemungkinan query profil header (follower count, view count) -- bukan feed/post."""
    text = str(payload)
    return "follower_count" in text and "text_post_app_public_view" in text


def detect_blocking_signals(payload: dict) -> Optional[str]:
    """Deteksi tanda-tanda pembatasan akun/IP (rate-limit, checkpoint, challenge) di response mentah."""
    text = str(payload).lower()
    signals = [
        "challenge_required", "checkpoint_required", "feedback_required",
        "consent_required", "suspicious_login_reason",
        '"error_type"', '"require_login"',
    ]
    for sig in signals:
        if sig in text:
            return sig
    return None


def extract_embedded_json_candidates(html: str) -> Iterator[dict]:
    """Cari blok JSON yang ditanam di HTML (pola SSR umum."""
    for match in re.finditer(
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            yield json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

    for match in re.finditer(
        r"window\.__[A-Za-z0-9_]+__\s*=\s*(\{.*?\})\s*;",
        html, re.DOTALL,
    ):
        try:
            yield json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue


def extract_profile_fields(payload: dict) -> Optional[dict]:
    """Cari dict user pertama yang memuat follower_count & view count."""

    def _walk(node: Any) -> Optional[dict]:
        if isinstance(node, dict):
            if "follower_count" in node:
                views = None
                tpv = node.get("text_post_app_public_views")
                if isinstance(tpv, dict):
                    raw = tpv.get("text_post_app_public_view_count")
                    if raw is not None:
                        try:
                            views = int(raw)
                        except (TypeError, ValueError):
                            views = None
                return {
                    "user_id": node.get("pk") or node.get("id"),
                    "username": node.get("username"),
                    "follower_count": node.get("follower_count"),
                    "view_count": views,
                }
            for value in node.values():
                result = _walk(value)
                if result is not None:
                    return result
        elif isinstance(node, list):
            for item in node:
                result = _walk(item)
                if result is not None:
                    return result
        return None

    return _walk(payload)


def classify_post_node(post: dict, source: str) -> dict:
    """Ubah satu node post mentah menjadi field-field yang kita perlukan, konsisten dengan models.RawPost."""

    tpi = post.get("text_post_app_info") or {}
    caption = post.get("caption") or {}
    user = post.get("user") or {}
    tag_header = tpi.get("tag_header") or {}

    is_partial_schema = "is_reply" not in tpi or "caption" not in post

    media_type = post.get("media_type")
    has_media = bool(
        media_type not in (None, _MEDIA_ABSENT_TYPE)
        or (post.get("image_versions2") or {}).get("candidates")
        or post.get("video_versions")
        or post.get("carousel_media")
    )

    return {
        "pk": str(post.get("pk")),
        "code": post.get("code"),
        "taken_at": post.get("taken_at"),
        "caption_text": caption.get("text") or "",
        "user_id": str(user.get("pk") or user.get("id") or ""),
        "username": user.get("username") or "",
        "is_reply": bool(tpi.get("is_reply", False)),
        "tag_header_name": tag_header.get("display_name"),
        "reposted_post_pk": reposted_post_pk(post),
        "has_media": has_media,
        "like_count": post.get("like_count") or 0,
        "direct_reply_count": tpi.get("direct_reply_count") or 0,
        "repost_count": tpi.get("repost_count") or 0,
        "is_partial_schema": is_partial_schema,
        "source": source,
    }


def matches_topic_criteria(tag_header_name: Optional[str], caption_text: str) -> bool:
    """Kriteria relevansi topik terkunci."""
    if tag_header_name and tag_header_name.strip().lower() == config.TAG_NAME:
        return True
    if caption_text and config.LITERAL_TAG_PATTERN.search(caption_text):
        return True
    return False
