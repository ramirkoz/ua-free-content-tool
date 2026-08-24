from __future__ import annotations

import logging
import time
from urllib.parse import quote, urlencode

from . import facebook_comments_v1_2_rc3 as facebook_comments
from . import instagram_target_v1_2_rc4 as instagram_target_module
from . import linkedin_comments_v1_2_rc3 as linkedin_comments
from . import threads_comments_v1_2_rc3 as threads_comments
from .comment_compat_v1_2_rc3 import CompatibleTelegramPublisher
from .donation_settings_v1_3_1_rc8 import DonationSettings, strip_known_donation_blocks, with_inline_donation
from .facebook_comments_v1_2_rc3 import CommentedFacebookPublisher
from .instagram_target_v1_2_rc4 import InstagramTarget
from .linkedin_comments_v1_2_rc3 import CommentedLinkedInPublisher
from .media_gallery_v1_2_rc4 import ImageGalleryPayload
from .models import MediaPayload
from .network import NetworkError, fetch_url
from .publishers import PublishContext, PublishError, PublishResult, Publisher
from .safe_publishers_v1_2 import SafePublisherFactory
from .threads_comments_v1_2_rc3 import CommentedThreadsPublisher
from .editorial_memory import split_threads_chain


logger = logging.getLogger("content_agent.publishers.rc8")


def _normalized_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split()).strip()


def _capturing_context(
    original: PublishContext,
    latest: dict[str, object],
) -> PublishContext:
    def save_progress(progress: dict[str, object]) -> None:
        latest.clear()
        latest.update(progress)
        original.save_progress(progress)

    return PublishContext(before_write=original.before_write, save_progress=save_progress)


def _save_donation_outcome(
    context: PublishContext,
    latest: dict[str, object],
    *,
    status: str,
    error: BaseException | str | None = None,
) -> dict[str, object]:
    updated = dict(latest)
    updated["donation_status"] = status
    if error is not None and str(error).strip():
        updated["donation_error"] = " ".join(str(error).split())[:1000]
    else:
        updated.pop("donation_error", None)
    context.save_progress(updated)
    latest.clear()
    latest.update(updated)
    return updated


def _threads_recent_match(user_id: str, token: str, expected_text: str) -> tuple[str, str] | None:
    """Find exactly one recent Threads post with the expected normalized text.

    Meta can return code 24/subcode 4279009 after the post is already visible.
    Reconciliation is deliberately conservative: an exact text match must be
    unique inside the recent-post window or we refuse to guess.
    """

    expected = _normalized_text(expected_text)
    if not expected:
        return None
    url = (
        f"https://graph.threads.net/v1.0/{quote(user_id, safe='')}/threads?"
        + urlencode({"fields": "id,text,timestamp,permalink", "limit": "25"})
    )
    response = fetch_url(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        max_bytes=3 * 1024 * 1024,
        allowed_content_types={"application/json", "text/javascript"},
        timeout=20,
        max_redirects=0,
        allow_http_errors=True,
    )
    payload = response.json() if response.body else {}
    if response.status >= 400 or not isinstance(payload, dict):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list):
        return None
    matches: list[tuple[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _normalized_text(str(row.get("text") or "")) != expected:
            continue
        remote_id = str(row.get("id") or "").strip()
        if remote_id:
            matches.append((remote_id, str(row.get("permalink") or "").strip()))
    return matches[0] if len(matches) == 1 else None


class Rc8FacebookPublisher(Publisher):
    def __init__(self, inner: CommentedFacebookPublisher, *, donation_text: str, enabled: bool):
        self.inner = inner
        self.donation_text = str(donation_text or "").strip()
        self.enabled = bool(enabled and self.donation_text)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        clean = strip_known_donation_blocks(text)
        latest = dict(progress)
        proxy = _capturing_context(context, latest)
        old = facebook_comments.DONATION_COMMENT
        facebook_comments.DONATION_COMMENT = self.donation_text if self.enabled else ""
        try:
            result = self.inner.publish(clean, latest, proxy, media)
            if self.enabled:
                latest = _save_donation_outcome(proxy, dict(result.progress), status="sent")
                return PublishResult(remote_id=result.remote_id, progress=latest)
            latest = _save_donation_outcome(proxy, dict(result.progress), status="disabled")
            return PublishResult(remote_id=result.remote_id, progress=latest)
        except Exception as exc:
            main_id = str(latest.get("facebook_donation_main_id") or "").strip()
            donation_phase = bool(
                latest.get("facebook_donation_comment_started")
                or latest.get("facebook_donation_comment_completed")
                or "донат" in str(exc).casefold()
            )
            if main_id and donation_phase:
                logger.warning("Facebook main post succeeded; donation phase failed: %s", exc)
                latest = _save_donation_outcome(proxy, latest, status="failed", error=exc)
                return PublishResult(remote_id=main_id, progress=latest)
            raise
        finally:
            facebook_comments.DONATION_COMMENT = old


class Rc8ThreadsPublisher(Publisher):
    def __init__(self, inner: CommentedThreadsPublisher, *, donation_text: str, enabled: bool):
        self.inner = inner
        self.donation_text = str(donation_text or "").strip()
        self.enabled = bool(enabled and self.donation_text)

    def _reconcile_root_and_resume(
        self,
        clean: str,
        latest: dict[str, object],
        context: PublishContext,
        exc: Exception,
        media: MediaPayload | ImageGalleryPayload | None,
    ) -> PublishResult | None:
        """Recover a root post that Meta published but reported as failed.

        RC8 only reconciled one-part text posts. RC12 also handles multi-part
        chains and media/gallery roots, then resumes from part 2 without
        creating a duplicate root. A short bounded retry covers Threads'
        eventual-consistency delay before a new post appears in /threads.
        """

        parts = split_threads_chain(clean, 500)
        if not parts:
            return None
        outcome_unknown = bool(getattr(exc, "outcome_unknown", False))
        code = getattr(exc, "code", None)
        subcode = getattr(exc, "subcode", None)
        known_meta_ambiguity = code == 24 and subcode == 4279009
        if not outcome_unknown and not known_meta_ambiguity:
            return None

        matched: tuple[str, str] | None = None
        for attempt in range(3):
            try:
                matched = _threads_recent_match(self.inner.user_id, self.inner.token, parts[0])
            except (NetworkError, PublishError, ValueError):
                matched = None
            if matched is not None:
                break
            if attempt < 2:
                time.sleep(2.0)
        if matched is None:
            return None

        remote_id, permalink = matched
        updated = dict(latest)
        updated.pop("container_id", None)
        updated.pop("container_part_index", None)
        updated.update(
            {
                "published_parts": 1,
                "total_parts": len(parts),
                "remote_ids": [remote_id],
                "threads_reconciled": True,
                "threads_permalink": permalink,
            }
        )
        if isinstance(media, ImageGalleryPayload):
            updated["threads_gallery_remote_id"] = remote_id
            updated["threads_gallery_publish_started"] = False
        context.save_progress(updated)
        latest.clear()
        latest.update(updated)
        logger.warning(
            "Threads ambiguous API outcome reconciled to existing root post %s; resuming remaining parts=%d",
            remote_id,
            max(0, len(parts) - 1),
        )

        try:
            resumed = self.inner.publish(clean, latest, context, media)
        except Exception as resume_exc:
            current_ids = latest.get("remote_ids") if isinstance(latest.get("remote_ids"), list) else []
            current_root = str(current_ids[0] if current_ids else latest.get("threads_gallery_remote_id") or remote_id).strip()
            donation_phase = bool(
                latest.get("threads_donation_comment_started")
                or latest.get("threads_donation_comment_completed")
                or latest.get("threads_donation_container_id")
                or "донат" in str(resume_exc).casefold()
            )
            all_parts_done = int(latest.get("published_parts", 0) or 0) >= len(parts)
            if current_root and donation_phase and all_parts_done:
                latest = _save_donation_outcome(context, latest, status="failed", error=resume_exc)
                return PublishResult(remote_id=current_root, progress=latest)
            raise

        final_progress = dict(resumed.progress)
        status = "sent" if self.enabled else "disabled"
        final_progress = _save_donation_outcome(context, final_progress, status=status)
        return PublishResult(remote_id=resumed.remote_id or remote_id, progress=final_progress)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        clean = strip_known_donation_blocks(text)
        latest = dict(progress)
        proxy = _capturing_context(context, latest)
        old = threads_comments.THREADS_FUND_FOOTER
        threads_comments.THREADS_FUND_FOOTER = self.donation_text if self.enabled else ""
        try:
            result = self.inner.publish(clean, latest, proxy, media)
            if self.enabled:
                latest = _save_donation_outcome(proxy, dict(result.progress), status="sent")
                return PublishResult(remote_id=result.remote_id, progress=latest)
            latest = _save_donation_outcome(proxy, dict(result.progress), status="disabled")
            return PublishResult(remote_id=result.remote_id, progress=latest)
        except Exception as exc:
            remote_ids = latest.get("remote_ids") if isinstance(latest.get("remote_ids"), list) else []
            root_id = str(remote_ids[0] if remote_ids else latest.get("threads_gallery_remote_id") or "").strip()
            donation_phase = bool(
                latest.get("threads_donation_comment_started")
                or latest.get("threads_donation_comment_completed")
                or latest.get("threads_donation_container_id")
                or "донат" in str(exc).casefold()
            )
            if root_id and donation_phase:
                logger.warning("Threads main post succeeded; donation phase failed: %s", exc)
                latest = _save_donation_outcome(proxy, latest, status="failed", error=exc)
                return PublishResult(remote_id=root_id, progress=latest)
            reconciled = self._reconcile_root_and_resume(clean, latest, proxy, exc, media)
            if reconciled is not None:
                return reconciled
            raise
        finally:
            threads_comments.THREADS_FUND_FOOTER = old


class Rc8LinkedInPublisher(Publisher):
    def __init__(self, inner: CommentedLinkedInPublisher, *, donation_text: str, enabled: bool):
        self.inner = inner
        self.donation_text = str(donation_text or "").strip()
        self.enabled = bool(enabled and self.donation_text)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        prepared = with_inline_donation(text, self.donation_text, self.enabled)
        old = linkedin_comments.DONATION_COMMENT
        linkedin_comments.DONATION_COMMENT = ""  # RC8 always handles LinkedIn donation inline.
        try:
            result = self.inner.publish(prepared, progress, context, media)
            updated = dict(result.progress)
            updated["donation_status"] = "inline" if self.enabled else "disabled"
            context.save_progress(updated)
            return PublishResult(remote_id=result.remote_id, progress=updated)
        finally:
            linkedin_comments.DONATION_COMMENT = old


class Rc8TelegramPublisher(Publisher):
    def __init__(self, inner: CompatibleTelegramPublisher, *, donation_text: str, enabled: bool):
        self.inner = inner
        self.donation_text = str(donation_text or "").strip()
        self.enabled = bool(enabled and self.donation_text)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        prepared = with_inline_donation(text, self.donation_text, self.enabled)
        result = self.inner.publish(prepared, progress, context, media)
        updated = dict(result.progress)
        updated["donation_status"] = "inline" if self.enabled else "disabled"
        context.save_progress(updated)
        return PublishResult(remote_id=result.remote_id, progress=updated)


class Rc8InstagramPublisher(Publisher):
    def __init__(self, inner: InstagramTarget, *, donation_text: str, enabled: bool):
        self.inner = inner
        self.donation_text = str(donation_text or "").strip()
        self.enabled = bool(enabled and self.donation_text)

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | ImageGalleryPayload | None = None,
    ) -> PublishResult:
        clean = strip_known_donation_blocks(text)
        old = instagram_target_module.FUND_FOOTER
        instagram_target_module.FUND_FOOTER = self.donation_text if self.enabled else ""
        try:
            result = self.inner.publish(clean, progress, context, media)
            updated = dict(result.progress)
            updated["donation_status"] = "inline" if self.enabled else "disabled"
            context.save_progress(updated)
            return PublishResult(remote_id=result.remote_id, progress=updated)
        finally:
            instagram_target_module.FUND_FOOTER = old


class Rc8PublisherFactory(SafePublisherFactory):
    """RC8 factory: current platform transport plus editable per-target donation policy."""

    def __init__(self, config, donation_settings: DonationSettings):
        super().__init__(config)
        self.donation_settings = donation_settings

    def update_donation_settings(self, settings: DonationSettings) -> None:
        self.donation_settings = settings

    def _policy(self, platform: str) -> tuple[str, bool]:
        settings = self.donation_settings.normalized()
        return settings.text, settings.enabled_for(platform)

    def create(self, platform: str) -> Publisher:
        donation_text, enabled = self._policy(platform)
        if platform == "telegram":
            return Rc8TelegramPublisher(
                CompatibleTelegramPublisher(self.config.telegram_bot_token, self.config.telegram_chat_id),
                donation_text=donation_text,
                enabled=enabled,
            )
        if platform.startswith("facebook:"):
            page_id = platform.split(":", 1)[1]
            page = self.config.facebook_page(page_id)
            if page is None and platform == "facebook:1" and self.config.facebook_page_1_id:
                page = {
                    "id": self.config.facebook_page_1_id,
                    "access_token": self.config.facebook_page_1_token,
                }
            if page is None and platform == "facebook:2" and self.config.facebook_page_2_id:
                page = {
                    "id": self.config.facebook_page_2_id,
                    "access_token": self.config.facebook_page_2_token,
                }
            if page is not None:
                return Rc8FacebookPublisher(
                    CommentedFacebookPublisher(page["id"], page["access_token"], self.config.meta_graph_version),
                    donation_text=donation_text,
                    enabled=enabled,
                )
        if platform == "threads":
            return Rc8ThreadsPublisher(
                CommentedThreadsPublisher(self.config.threads_user_id, self.config.threads_token),
                donation_text=donation_text,
                enabled=enabled,
            )
        if platform == "linkedin":
            return Rc8LinkedInPublisher(
                CommentedLinkedInPublisher(
                    self.config.linkedin_author_urn,
                    self.config.linkedin_token,
                    self.config.linkedin_version,
                ),
                donation_text=donation_text,
                enabled=enabled,
            )
        if platform == "instagram":
            if not self.config.instagram_enabled:
                raise PublishError("Instagram вимкнено в налаштуваннях.", retryable=False, auth_error=True)
            return Rc8InstagramPublisher(
                InstagramTarget(
                    self.config.instagram_user_id,
                    self.config.instagram_token,
                    self.config.meta_graph_version,
                ),
                donation_text=donation_text,
                enabled=enabled,
            )
        return super().create(platform)
