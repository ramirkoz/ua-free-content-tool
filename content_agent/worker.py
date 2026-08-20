from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .database import Database, LeaseLost
from .google_drive import DriveMediaInfo, GoogleDriveClient, GoogleDriveError
from .models import MediaPayload, PublicationTarget
from .network import NetworkError
from .publishers import PublishContext, PublishError, PublishResult, Publisher, PublisherFactory
from .security import redact_secrets

logger = logging.getLogger("content_agent.worker")


class PublicationCancelRequested(RuntimeError):
    """Cooperative stop requested before another external platform write."""


@dataclass(slots=True)
class WorkerResult:
    claimed: bool
    batch_id: int | None = None
    completed: bool = False
    busy: bool = False
    paused: bool = False
    pause_reason: str = ""
    sent_targets: int = 0
    failed_targets: int = 0
    sent_platforms: list[str] = field(default_factory=list)
    failed_platforms: dict[str, str] = field(default_factory=dict)
    auth_failed_platforms: list[str] = field(default_factory=list)


class PublicationWorker:
    """Single-flight, paced publication worker.

    The background scheduler and the manual "run now" button share one worker.
    FIX18 allowed those two entry points to claim different packages at the same
    time. Targets inside one package were sequential, but two packages could
    still hit Meta concurrently. FIX19 closes that gap; FIX23 adds a cross-package auth circuit breaker with a process-local
    single-flight lock and an explicit inter-target pause.
    """

    def __init__(
        self,
        database: Database,
        factory: PublisherFactory,
        lease_seconds: int = 180,
        *,
        inter_target_delay_seconds: float = 0.0,
        max_automatic_attempts: int = 3,
        target_timeout_seconds: float = 120.0,
        media_target_timeout_seconds: float = 240.0,
        media_preflight_timeout_seconds: float = 60.0,
        progress_callback: Callable[[str], None] | None = None,
        result_callback: Callable[[WorkerResult], None] | None = None,
    ):
        self.database = database
        self.factory = factory
        self.lease_seconds = lease_seconds
        self.inter_target_delay_seconds = max(0.0, float(inter_target_delay_seconds))
        self.max_automatic_attempts = max(1, int(max_automatic_attempts))
        self.target_timeout_seconds = max(0.05, float(target_timeout_seconds))
        self.media_target_timeout_seconds = max(0.1, float(media_target_timeout_seconds))
        self.media_preflight_timeout_seconds = max(1.0, float(media_preflight_timeout_seconds))
        self.progress_callback = progress_callback
        self.result_callback = result_callback
        self._wake_event = threading.Event()
        self._run_lock = threading.Lock()
        self._auth_block_lock = threading.Lock()
        self._auth_blocks: dict[str, str] = {}
        self._inflight_lock = threading.Lock()
        self._inflight_targets: set[int] = set()
        self._cancel_lock = threading.Lock()
        self._cancel_requested_batches: set[int] = set()
        self._active_batch_id: int | None = None

    def active_batch_id(self) -> int | None:
        with self._cancel_lock:
            return self._active_batch_id

    def request_cancel(self, batch_id: int) -> bool:
        """Request a cooperative stop for the batch owned by this worker.

        A platform HTTP write cannot be killed safely. If one is already in
        flight, it is allowed to finish and no next target is started. Media
        preflight is read-only and can be abandoned immediately.
        """
        batch_id = int(batch_id)
        with self._cancel_lock:
            if self._active_batch_id != batch_id:
                return False
            self._cancel_requested_batches.add(batch_id)
        self.wake()
        return True

    def _set_active_batch(self, batch_id: int | None) -> None:
        with self._cancel_lock:
            self._active_batch_id = batch_id

    def _cancel_requested(self, batch_id: int) -> bool:
        with self._cancel_lock:
            return int(batch_id) in self._cancel_requested_batches

    def _clear_cancel_request(self, batch_id: int) -> None:
        with self._cancel_lock:
            self._cancel_requested_batches.discard(int(batch_id))
            if self._active_batch_id == int(batch_id):
                self._active_batch_id = None

    def _raise_if_cancel_requested(self, batch_id: int) -> None:
        if self._cancel_requested(batch_id):
            raise PublicationCancelRequested(f"Зупинку пакета #{batch_id} запрошено користувачем.")

    def wake(self) -> None:
        """Wake the background loop after the editor creates or changes a package."""
        self._wake_event.set()

    def _notify(self, message: str) -> None:
        logger.info(message)
        if self.progress_callback is not None:
            try:
                self.progress_callback(message)
            except Exception:
                logger.debug("Publication progress callback failed.", exc_info=True)

    @staticmethod
    def _auth_block_key(platform: str, exc: Exception | None = None) -> str:
        if platform.startswith("facebook:"):
            if exc is None:
                return "facebook:*"
            code = exc.code if isinstance(exc, PublishError) else None
            lowered = str(exc).lower()
            if code == 190 or "token" in lowered or "oauth" in lowered or "expired" in lowered:
                return "facebook:*"
        return platform

    def block_auth(self, platform: str, reason: str, exc: Exception | None = None) -> None:
        key = self._auth_block_key(platform, exc)
        safe = redact_secrets(reason)[:1000]
        with self._auth_block_lock:
            self._auth_blocks[key] = safe

    def clear_auth_blocks(self, *platforms: str) -> None:
        """Clear cached credential failures after the user replaces a token."""
        with self._auth_block_lock:
            if not platforms:
                self._auth_blocks.clear()
                return
            for platform in platforms:
                if platform == "facebook" or platform.startswith("facebook:"):
                    self._auth_blocks.pop("facebook:*", None)
                    if platform.startswith("facebook:"):
                        self._auth_blocks.pop(platform, None)
                    else:
                        for key in list(self._auth_blocks):
                            if key.startswith("facebook:"):
                                self._auth_blocks.pop(key, None)
                else:
                    self._auth_blocks.pop(platform, None)

    def auth_block_reason(self, platform: str) -> str:
        with self._auth_block_lock:
            if platform.startswith("facebook:") and "facebook:*" in self._auth_blocks:
                return self._auth_blocks["facebook:*"]
            return self._auth_blocks.get(platform, "")

    def _emit_result(self, result: WorkerResult) -> None:
        if self.result_callback is None:
            return
        try:
            self.result_callback(result)
        except Exception:
            logger.debug("Publication result callback failed.", exc_info=True)

    def _drive_client(self) -> GoogleDriveClient:
        config = self.factory.config
        return GoogleDriveClient(config.google_client_id, config.google_client_secret, config.google_refresh_token)

    def _load_media(
        self, batch_article_id: int
    ) -> tuple[MediaPayload | None, GoogleDriveClient | None, int, DriveMediaInfo | None]:
        group_id = self.database.group_id_for_article(batch_article_id)
        group = self.database.get_group(group_id)
        if not group.media_file_id:
            return None, None, group_id, None
        client = self._drive_client()
        # Re-read current Drive capabilities. A file may be private, moved or have
        # different sharing permissions by the time its queue slot becomes due.
        info = client.inspect_media(group.media_file_id)
        data = client.download_media(info)
        return (
            MediaPayload(
                file_id=info.file_id,
                name=info.name,
                kind=info.kind,
                mime_type=info.mime_type,
                data=data,
                public_url=info.public_url,
            ),
            client,
            group_id,
            info,
        )

    def _load_media_cancellable(
        self, *, batch_id: int, batch_article_id: int, owner: str
    ) -> tuple[MediaPayload | None, GoogleDriveClient | None, int, DriveMediaInfo | None]:
        """Run Drive preflight outside SQLite locks with a cancellable hard bound.

        Drive reads have no publication side effects, so a timed-out/background
        read can safely be abandoned without risking a duplicate social post.
        """
        done = threading.Event()
        result_holder: list[tuple[MediaPayload | None, GoogleDriveClient | None, int, DriveMediaInfo | None]] = []
        error_holder: list[BaseException] = []

        def runner() -> None:
            try:
                result_holder.append(self._load_media(batch_article_id))
            except BaseException as exc:
                error_holder.append(exc)
            finally:
                done.set()

        threading.Thread(
            target=runner,
            name=f"drive-preflight-{batch_id}",
            daemon=True,
        ).start()
        deadline = time.monotonic() + self.media_preflight_timeout_seconds
        next_renew = time.monotonic() + min(20.0, max(5.0, self.media_preflight_timeout_seconds / 3.0))
        while not done.wait(0.2):
            self._raise_if_cancel_requested(batch_id)
            now = time.monotonic()
            if now >= deadline:
                raise GoogleDriveError(
                    f"Google Drive не завершив підготовку медіа за {int(self.media_preflight_timeout_seconds)} секунд."
                )
            if now >= next_renew:
                self.database.assert_lease(batch_id, owner)
                self.database.renew_lease(batch_id, owner, self.lease_seconds)
                next_renew = now + 20.0
        self._raise_if_cancel_requested(batch_id)
        if error_holder:
            raise error_holder[0]
        if not result_holder:
            raise GoogleDriveError("Google Drive завершив підготовку медіа без результату.")
        return result_holder[0]

    def _facebook_order(self) -> dict[str, int]:
        config = self.factory.config
        order: dict[str, int] = {}
        for index, row in enumerate(config.facebook_pages):
            if isinstance(row, dict) and row.get("id"):
                order[str(row["id"])] = index
        # Keep old portable packages deterministic even when they still use the
        # two legacy aliases.
        if config.facebook_page_1_id:
            order.setdefault(str(config.facebook_page_1_id), len(order))
        if config.facebook_page_2_id:
            order.setdefault(str(config.facebook_page_2_id), len(order))
        return order

    def _target_sort_key(self, target: PublicationTarget) -> tuple[int, int, int]:
        platform = target.platform
        if platform.startswith("facebook:"):
            page_id = platform.split(":", 1)[1]
            legacy = {"1": 0, "2": 1}
            page_order = self._facebook_order()
            return (0, page_order.get(page_id, legacy.get(page_id, 10_000)), target.id)
        if platform == "threads":
            return (1, 0, target.id)
        if platform == "linkedin":
            return (2, 0, target.id)
        if platform == "telegram":
            return (3, 0, target.id)
        return (4, 0, target.id)

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, PublishError):
            return bool(exc.retryable)
        if isinstance(exc, NetworkError):
            return True
        text = str(exc).lower()
        permanent_markers = (
            "invalid oauth",
            "access token",
            "token is required",
            "not configured",
            "permission",
            "administrator",
            "chat not found",
            "forbidden",
            "unsupported publication platform",
        )
        return not any(marker in text for marker in permanent_markers)

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        if isinstance(exc, PublishError):
            return bool(exc.auth_error)
        text = str(exc).lower()
        return "token" in text or "oauth" in text or "permission" in text or "administrator" in text

    @staticmethod
    def _is_meta_platform(platform: str) -> bool:
        return platform.startswith("facebook:") or platform == "threads"

    def _paced_wait(self, batch_id: int, owner: str, next_platform: str) -> None:
        remaining = self.inter_target_delay_seconds
        if remaining <= 0:
            return
        self.database.assert_lease(batch_id, owner)
        self.database.renew_lease(batch_id, owner, self.lease_seconds)
        while remaining > 0:
            self._raise_if_cancel_requested(batch_id)
            shown = max(1, int(remaining + 0.999))
            self._notify(f"Пауза перед наступною платформою: {shown} с · далі {next_platform}")
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step
        self.database.assert_lease(batch_id, owner)
        self.database.renew_lease(batch_id, owner, self.lease_seconds)

    def _has_inflight_targets(self) -> bool:
        with self._inflight_lock:
            return bool(self._inflight_targets)

    def _publish_with_timeout(
        self,
        *,
        batch_id: int,
        owner: str,
        target: PublicationTarget,
        publisher: Publisher,
        payload_text: str,
        media: MediaPayload | None,
    ) -> PublishResult:
        """Run one platform call outside SQLite locks with a hard upper bound.

        Python cannot safely kill a thread blocked inside an OS/network call. On
        timeout the target is therefore marked as an *unknown outcome* and the
        batch is paused. The daemon thread may finish later, but it cannot update
        queue state and no new package is started while it is still alive.
        """

        target_id = int(target.id)
        with self._inflight_lock:
            if target_id in self._inflight_targets:
                raise PublishError(
                    "Попередній запит цієї цілі ще не завершився. Перевірте платформу вручну й перезапустіть програму перед повтором.",
                    retryable=False,
                    outcome_unknown=True,
                )
            self._inflight_targets.add(target_id)

        timeout = self.media_target_timeout_seconds if media is not None else self.target_timeout_seconds
        cancelled = threading.Event()
        done = threading.Event()
        result_holder: list[PublishResult] = []
        error_holder: list[BaseException] = []

        def before_write() -> None:
            if cancelled.is_set():
                raise LeaseLost("Publication call was cancelled after timeout.")
            self.database.assert_lease(batch_id, owner)
            self.database.renew_lease(
                batch_id, owner, max(self.lease_seconds, int(timeout) + 60)
            )

        def save_progress(progress: dict[str, object]) -> None:
            if cancelled.is_set():
                raise LeaseLost("Publication call was cancelled after timeout.")
            self.database.assert_lease(batch_id, owner)
            self.database.save_target_progress(target_id, progress)

        context = PublishContext(before_write=before_write, save_progress=save_progress)

        def runner() -> None:
            try:
                if media is None:
                    value = publisher.publish(payload_text, dict(target.progress), context)
                else:
                    value = publisher.publish(payload_text, dict(target.progress), context, media)
                result_holder.append(value)
            except BaseException as exc:
                error_holder.append(exc)
            finally:
                with self._inflight_lock:
                    self._inflight_targets.discard(target_id)
                done.set()
                self.wake()

        threading.Thread(
            target=runner,
            name=f"publish-target-{target_id}-{target.platform}",
            daemon=True,
        ).start()

        if not done.wait(timeout):
            cancelled.set()
            raise PublishError(
                f"{target.platform} не завершив запит за {int(timeout)} секунд. "
                "Результат невідомий: перевірте платформу вручну. Автоматичний повтор вимкнено, щоб не створити дубль.",
                retryable=False,
                outcome_unknown=True,
            )
        if error_holder:
            error = error_holder[0]
            if isinstance(error, BaseException):
                raise error
        if not result_holder:
            raise PublishError(
                f"{target.platform} завершився без результату.", retryable=False
            )
        return result_holder[0]

    def run_once(self) -> WorkerResult:
        # A timed-out OS request may still be alive in a daemon thread. Starting
        # another package before it exits could duplicate a publication.
        if self._has_inflight_targets():
            return WorkerResult(
                claimed=False,
                busy=True,
                pause_reason="Попередній мережевий запит ще завершується у фоні.",
            )
        if not self._run_lock.acquire(blocking=False):
            return WorkerResult(claimed=False, busy=True)
        try:
            return self._run_once_locked()
        finally:
            self._run_lock.release()

    def _run_once_locked(self) -> WorkerResult:
        # Do not hold DATA_MAINTENANCE_LOCK during external HTTP calls. Database
        # methods take short locks of their own; keeping the global lock across a
        # network request was the direct cause of the frozen interface in FIX25.
        owner = str(uuid.uuid4())
        self.database.pause_exhausted_batches(self.max_automatic_attempts)
        batch = self.database.claim_due_batch(owner=owner, lease_seconds=self.lease_seconds)
        if not batch:
            return WorkerResult(claimed=False)
        self._set_active_batch(batch.id)
        result = WorkerResult(claimed=True, batch_id=batch.id)
        media: MediaPayload | None = None
        drive_client: GoogleDriveClient | None = None
        media_info: DriveMediaInfo | None = None
        temporary_permission_id = ""
        media_deleted = False
        group_id = self.database.group_id_for_article(batch.article_id)
        pause_after_run = False
        pause_reasons: list[str] = []
        meta_rate_limited = False
        abort_after_unknown = False
        try:
            active_targets = sorted(
                (target for target in batch.targets if target.status != "sent"),
                key=self._target_sort_key,
            )
            self._raise_if_cancel_requested(batch.id)
            if active_targets:
                try:
                    media, drive_client, group_id, media_info = self._load_media_cancellable(
                        batch_id=batch.id, batch_article_id=batch.article_id, owner=owner
                    )
                except PublicationCancelRequested:
                    self.database.cancel_claimed_batch(batch.id, owner)
                    self._notify(f"Пакет #{batch.id}: скасовано до початку публікації.")
                    return result
                except Exception as exc:
                    safe_error = "Google Drive / медіа: " + redact_secrets(exc)[:900]
                    logger.warning("Publication preflight failed batch=%s: %s", batch.id, safe_error)
                    self.database.mark_unsent_targets_failed(batch.id, safe_error)
                    result.failed_targets += len(active_targets)
                    for item in active_targets:
                        result.failed_platforms[item.platform] = safe_error
                    result.completed = self.database.finish_batch(
                        batch.id, owner, max_automatic_attempts=self.max_automatic_attempts
                    )
                    final_batch = self.database.get_batch(batch.id)
                    result.paused = final_batch.status == "paused"
                    if result.paused:
                        result.pause_reason = (
                            f"Google Drive недоступний. Автоматичні спроби зупинено після {final_batch.attempts} запусків."
                        )
                    self._notify(f"Пакет #{batch.id}: {safe_error}")
                    return result
            self._raise_if_cancel_requested(batch.id)
            if (
                media is not None
                and drive_client is not None
                and media_info is not None
                and any(target.platform == "threads" for target in active_targets)
            ):
                temporary_permission_id = drive_client.ensure_public_for_threads(media_info)

            attempted = 0
            total = len(active_targets)
            for target in active_targets:
                if self._cancel_requested(batch.id):
                    self.database.cancel_claimed_batch(batch.id, owner)
                    self._notify(f"Пакет #{batch.id}: зупинено перед наступною платформою.")
                    return result
                blocked_reason = self.auth_block_reason(target.platform)
                if blocked_reason:
                    attempted += 1
                    skipped_error = (
                        "Пропущено без нового запиту: для цієї платформи вже зафіксовано недійсний "
                        "токен або відсутні права. Оновіть підключення, потім відновіть призупинені пакети. "
                        f"Причина: {blocked_reason}"
                    )
                    self.database.mark_target_failed(target.id, skipped_error)
                    result.failed_targets += 1
                    result.failed_platforms[target.platform] = skipped_error
                    result.auth_failed_platforms.append(target.platform)
                    pause_after_run = True
                    pause_reasons.append(f"{target.platform}: {skipped_error}")
                    self._notify(
                        f"Пакет #{batch.id}, ціль #{target.id}: пропущено {target.platform}, токен уже заблоковано"
                    )
                    continue
                if meta_rate_limited and self._is_meta_platform(target.platform):
                    attempted += 1
                    deferred_error = (
                        "Meta тимчасово обмежила частоту запитів. Цю платформу не викликали повторно "
                        "в тому самому проході; наступна контрольована спроба буде після паузи."
                    )
                    self.database.mark_target_failed(target.id, deferred_error)
                    result.failed_targets += 1
                    result.failed_platforms[target.platform] = deferred_error
                    self._notify(
                        f"Пакет #{batch.id}, ціль #{target.id}: відкладено {target.platform}, ліміт Meta"
                    )
                    continue
                if attempted:
                    self._paced_wait(batch.id, owner, target.platform)
                attempted += 1
                self._notify(
                    f"Пакет #{batch.id}, ціль #{target.id}: публікація {attempted}/{total}: {target.platform}"
                )
                self.database.assert_lease(batch.id, owner)

                try:
                    publisher = self.factory.create(target.platform)
                    payload_text = self.database.target_payload(target.id)
                    publication = self._publish_with_timeout(
                        batch_id=batch.id,
                        owner=owner,
                        target=target,
                        publisher=publisher,
                        payload_text=payload_text,
                        media=media,
                    )
                    self.database.assert_lease(batch.id, owner)
                    self.database.mark_target_sent(target.id, publication.remote_id)
                    result.sent_targets += 1
                    result.sent_platforms.append(target.platform)
                    self._notify(
                        f"Пакет #{batch.id}, ціль #{target.id}: опубліковано: {target.platform}"
                    )
                    if self._cancel_requested(batch.id):
                        self.database.cancel_claimed_batch(batch.id, owner)
                        self._notify(
                            f"Пакет #{batch.id}: поточний запит завершився; решту платформ скасовано."
                        )
                        return result
                except LeaseLost:
                    raise
                except Exception as exc:
                    self.database.assert_lease(batch.id, owner)
                    self.database.mark_target_failed(target.id, exc)
                    safe_error = redact_secrets(exc)[:1000]
                    logger.warning(
                        "Publication target failed batch=%s target=%s platform=%s: %s",
                        batch.id, target.id, target.platform, safe_error,
                    )
                    result.failed_targets += 1
                    result.failed_platforms[target.platform] = safe_error
                    if self._is_auth_error(exc):
                        result.auth_failed_platforms.append(target.platform)
                        self.block_auth(target.platform, safe_error, exc)
                    if isinstance(exc, PublishError) and exc.rate_limited and self._is_meta_platform(target.platform):
                        meta_rate_limited = True
                    if not self._is_retryable(exc):
                        pause_after_run = True
                        pause_reasons.append(f"{target.platform}: {safe_error}")
                    if isinstance(exc, PublishError) and exc.outcome_unknown:
                        abort_after_unknown = True
                        pause_after_run = True
                        pause_reasons.append(
                            "Зупинено пакет після невідомого результату, щоб не створити дублікати."
                        )
                    self._notify(
                        f"Пакет #{batch.id}, ціль #{target.id}: помилка {target.platform}: {safe_error}"
                    )
                    if abort_after_unknown:
                        break

            if self.database.all_targets_sent(batch.id):
                group = self.database.get_group(group_id)
                if group.media_file_id:
                    try:
                        self.database.assert_lease(batch.id, owner)
                        self.database.renew_lease(batch.id, owner, self.lease_seconds)
                        cleanup_client = drive_client or self._drive_client()
                        cleanup_client.delete_file(group.media_file_id)
                        media_deleted = True
                        self.database.clear_group_media(group_id)
                    except LeaseLost:
                        raise
                    except Exception as exc:
                        logger.warning("Media cleanup deferred for batch %s: %s", batch.id, exc)
                        self.database.defer_cleanup(
                            batch.id, owner, exc, max_automatic_attempts=self.max_automatic_attempts
                        )
                        final_batch = self.database.get_batch(batch.id)
                        result.paused = final_batch.status == "paused"
                        if result.paused:
                            result.pause_reason = "Google Drive cleanup призупинено після ліміту спроб."
                        return result
            result.completed = self.database.finish_batch(
                batch.id,
                owner,
                pause=pause_after_run,
                max_automatic_attempts=self.max_automatic_attempts,
            )
            if not result.completed:
                final_batch = self.database.get_batch(batch.id)
                result.paused = final_batch.status == "paused"
                if result.paused:
                    if pause_reasons:
                        result.pause_reason = "Потрібне втручання: " + " | ".join(pause_reasons)
                    else:
                        result.pause_reason = (
                            f"Автоматичні спроби зупинено після {final_batch.attempts} невдалих запусків."
                        )
            return result
        except PublicationCancelRequested:
            try:
                self.database.cancel_claimed_batch(batch.id, owner)
            except LeaseLost:
                pass
            self._notify(f"Пакет #{batch.id}: зупинено користувачем.")
            return result
        except LeaseLost:
            logger.warning("Publication lease lost; stopping batch %s before another write.", batch.id)
            return result
        except Exception as exc:
            safe_error = "Внутрішня помилка публікації: " + redact_secrets(exc)[:900]
            try:
                self.database.fail_claimed_batch(
                    batch.id, owner, safe_error, max_automatic_attempts=self.max_automatic_attempts
                )
            except LeaseLost:
                pass
            raise
        finally:
            self._clear_cancel_request(batch.id)
            if temporary_permission_id and not media_deleted and drive_client and media:
                for attempt in range(3):
                    try:
                        drive_client.remove_permission(media.file_id, temporary_permission_id)
                        break
                    except GoogleDriveError as exc:
                        if attempt == 2:
                            logger.error("Temporary Drive permission cleanup failed: %s", exc)

    def run_loop(self, stop_event: threading.Event, poll_seconds: float = 15.0) -> None:
        while not stop_event.is_set():
            try:
                outcome = self.run_once()
                worked = outcome.claimed
                busy = outcome.busy
                if worked or outcome.failed_targets or outcome.sent_targets or outcome.paused:
                    self._emit_result(outcome)
            except Exception as exc:
                logger.error("Publication worker iteration failed: %s", exc)
                worked = False
                busy = False
            if worked or busy:
                stop_event.wait(1.0)
                continue
            # Wait for either the normal polling interval or an explicit editor wake-up.
            # This keeps CPU use low without making a newly queued due package sit idle.
            self._wake_event.wait(poll_seconds)
            self._wake_event.clear()
