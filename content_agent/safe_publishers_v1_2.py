from __future__ import annotations

import json
from typing import Any

from .models import MediaPayload
from .network import NetworkError, fetch_url
from .publishers import (
    LinkedInPublisher,
    PublishContext,
    PublishError,
    PublishResult,
    Publisher,
    PublisherFactory,
    ThreadsPublisher,
    _check_payload,
)


def _linkedin_post_json(
    url: str,
    payload: dict[str, object],
    headers: dict[str, str],
    *,
    timeout: float = 60,
) -> tuple[dict[str, object], dict[str, str]]:
    """POST JSON to LinkedIn while accepting its valid empty 2xx responses.

    LinkedIn's create-post endpoint may return a successful response with no body
    and no Content-Type while the created post URN is carried in x-restli-id.
    The generic JSON helper rejects such a response before callers can inspect
    that header. That false failure caused repeated create POSTs in production.
    """

    response = fetch_url(
        url,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **headers},
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        max_bytes=3 * 1024 * 1024,
        allowed_content_types=None,
        timeout=timeout,
        max_redirects=0,
        allow_http_errors=True,
    )

    decoded: dict[str, object] = {}
    if response.body:
        actual = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        if actual not in {"application/json", "text/javascript"}:
            raise PublishError(
                f"LinkedIn повернув неочікуваний Content-Type: {actual or '<відсутній>'}.",
                retryable=response.status >= 500,
                outcome_unknown=response.status < 400,
            )
        try:
            value = response.json()
        except NetworkError as exc:
            raise PublishError(
                "LinkedIn повернув нечитабельну відповідь після створення публікації.",
                retryable=False,
                outcome_unknown=response.status < 400,
            ) from exc
        if not isinstance(value, dict):
            raise PublishError(
                "LinkedIn повернув некоректну відповідь після створення публікації.",
                retryable=False,
                outcome_unknown=response.status < 400,
            )
        decoded = value

    if response.status >= 400:
        if decoded:
            _check_payload(decoded, http_status=response.status)
        raise PublishError(
            f"LinkedIn request failed with HTTP {response.status}.",
            retryable=response.status == 429 or response.status >= 500,
            rate_limited=response.status == 429,
        )

    if decoded:
        decoded = _check_payload(decoded)
    return decoded, response.headers


class SafeLinkedInPublisher(LinkedInPublisher):
    """LinkedIn publisher with a durable no-duplicate write barrier."""

    _STARTED = "linkedin_write_started"
    _COMPLETED = "linkedin_write_completed"
    _POST_ID = "linkedin_post_id"
    _ENDPOINT = "linkedin_write_endpoint"

    @staticmethod
    def _unknown(message: str, exc: BaseException | None = None) -> PublishError:
        error = PublishError(
            "LinkedIn: результат публікації невідомий. Автоматичний повтор заблоковано, "
            "щоб не створити дубль. Перевірте профіль LinkedIn перед будь-якою новою публікацією. "
            f"Деталі: {message}",
            retryable=False,
            outcome_unknown=True,
        )
        if exc is not None:
            error.__cause__ = exc
        return error

    def _existing_result(self, progress: dict[str, object]) -> PublishResult | None:
        post_id = str(progress.get(self._POST_ID, "") or "").strip()
        if post_id and bool(progress.get(self._COMPLETED)):
            return PublishResult(remote_id=post_id, progress=progress)
        if bool(progress.get(self._STARTED)):
            raise self._unknown("попередня спроба почала create-POST, але підтверджений post ID не збережено")
        return None

    def _begin_write(
        self,
        progress: dict[str, object],
        context: PublishContext,
        endpoint: str,
    ) -> dict[str, object]:
        updated = {
            **progress,
            self._STARTED: True,
            self._COMPLETED: False,
            self._ENDPOINT: endpoint,
        }
        # Persist before the network write. If the process dies after the server
        # accepts the post, the next run sees the barrier and cannot POST again.
        context.save_progress(updated)
        context.before_write()
        return updated

    def _finish_write(
        self,
        progress: dict[str, object],
        context: PublishContext,
        remote_id: str,
    ) -> PublishResult:
        completed = {
            **progress,
            self._COMPLETED: True,
            self._POST_ID: remote_id,
        }
        # Persist remote ID before the worker flips target.status to sent. A crash
        # in that tiny window therefore recovers without another LinkedIn POST.
        context.save_progress(completed)
        return PublishResult(remote_id=remote_id, progress=completed)

    def _post_safely(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        progress: dict[str, object],
        context: PublishContext,
        timeout: float,
    ) -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
        progress = self._begin_write(progress, context, url)
        try:
            body, response_headers = _linkedin_post_json(
                url,
                payload,
                headers,
                timeout=timeout,
            )
        except PublishError as exc:
            if exc.outcome_unknown or exc.retryable:
                raise self._unknown(str(exc), exc)
            raise
        except NetworkError as exc:
            raise self._unknown(str(exc), exc)
        return body, response_headers, progress

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        existing = self._existing_result(progress)
        if existing is not None:
            return existing

        if not media:
            payload = {
                "author": self.author_urn,
                "commentary": text,
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            body, response_headers, progress = self._post_safely(
                url="https://api.linkedin.com/rest/posts",
                payload=payload,
                headers=self.headers,
                progress=progress,
                context=context,
                timeout=60,
            )
            remote_id = str(response_headers.get("x-restli-id") or body.get("id") or "").strip()
            if not remote_id:
                raise self._unknown("успішна відповідь не містить x-restli-id або id")
            return self._finish_write(progress, context, remote_id)

        asset = str(progress.get("asset", "") or "").strip()
        if not asset:
            asset = self._register_and_upload(media, context)
            progress = {**progress, "asset": asset}
            context.save_progress(progress)

        payload = {
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "IMAGE" if media.kind == "image" else "VIDEO",
                    "media": [
                        {
                            "status": "READY",
                            "media": asset,
                            "title": {"text": media.name[:200]},
                        }
                    ],
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }
        body, response_headers, progress = self._post_safely(
            url="https://api.linkedin.com/v2/ugcPosts",
            payload=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            progress=progress,
            context=context,
            timeout=120,
        )
        remote_id = str(response_headers.get("x-restli-id") or body.get("id") or "").strip()
        if not remote_id:
            raise self._unknown("успішна відповідь медіапублікації не містить post ID")
        return self._finish_write(progress, context, remote_id)


class SafeThreadsPublisher(ThreadsPublisher):
    """Stop blind retries when Meta gives the unhelpful literal UNKNOWN error."""

    def publish(
        self,
        text: str,
        progress: dict[str, object],
        context: PublishContext,
        media: MediaPayload | None = None,
    ) -> PublishResult:
        try:
            return super().publish(text, progress, context, media)
        except PublishError as exc:
            message = str(exc).strip()
            if message.casefold() == "unknown":
                raise PublishError(
                    "Threads API повернув помилку UNKNOWN під час створення або публікації. "
                    "Автоматичний повтор зупинено, бо сліпі повтори не дають нової діагностики. "
                    "Перевірте Threads і повторіть пакет лише після перевірки.",
                    retryable=False,
                ) from exc
            raise


class SafePublisherFactory(PublisherFactory):
    def create(self, platform: str) -> Publisher:
        if platform == "linkedin":
            return SafeLinkedInPublisher(
                self.config.linkedin_author_urn,
                self.config.linkedin_token,
                self.config.linkedin_version,
            )
        if platform == "threads":
            return SafeThreadsPublisher(self.config.threads_user_id, self.config.threads_token)
        return super().create(platform)
