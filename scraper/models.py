"""Struktur data inti yang dipakai lintas modul."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class RawPost:
    """Satu item post/reply yang ditemukan, baik dari hasil pencarian hashtag (source='search') maupun dari pemindaian
    feed akun (source='feed')."""

    pk: str
    code: Optional[str]
    taken_at: int
    caption_text: str
    user_id: str
    username: str
    is_reply: bool
    tag_header_name: Optional[str]
    reposted_post_pk: Optional[str]
    has_media: bool
    like_count: int
    direct_reply_count: int
    repost_count: int
    is_partial_schema: bool
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccountProfile:
    user_id: str
    username: str
    follower_count: Optional[int]
    view_count: Optional[int]
    fetched_at_utc: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FeedCounts:
    """Enam fitur akun window-bound."""

    user_id: str
    threads_count: int = 0
    replies_count: int = 0
    reposts_count: int = 0
    media_count: int = 0
    topic_threads_count: int = 0
    topic_replies_count: int = 0
    items_scanned: int = 0
    unclassifiable_items_count: int = 0
    stopped_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
