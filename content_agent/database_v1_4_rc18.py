from __future__ import annotations

from datetime import datetime

from .database import _iso
from .database_v1_4_rc15 import Database as Rc15Database
from .news_logic import calculate_explosiveness, is_today_kyiv, parse_published_at
from .scheduling import KYIV


class Database(Rc15Database):
    """RC18 keeps the working Inbox scoped to the current Kyiv calendar day.

    Historical material is never deleted. At day rollover, fully stale unqueued
    blocks are archived. If a pre-publication block contains both today's and
    older source stories, the older stories are moved into a separate archived
    block and the surviving current-day block is invalidated for a fresh rewrite.
    """

    @staticmethod
    def _article_is_today(published_at: str | None, discovered_at: str | None, *, now: datetime) -> bool:
        """Use source publication time first, then discovery time as a safe fallback."""
        published = parse_published_at(published_at)
        if published is not None:
            return published.astimezone(KYIV).date() == now.astimezone(KYIV).date()
        discovered = parse_published_at(discovered_at)
        if discovered is not None:
            return discovered.astimezone(KYIV).date() == now.astimezone(KYIV).date()
        return False

    @staticmethod
    def _article_sort_key(row: object) -> datetime:
        """Return an aware timestamp for deterministic newest-story selection."""
        try:
            published_at = row["published_at"]  # type: ignore[index]
            discovered_at = row["discovered_at"]  # type: ignore[index]
        except Exception:
            return datetime.min.replace(tzinfo=KYIV)
        parsed = parse_published_at(published_at) or parse_published_at(discovered_at)
        if parsed is None:
            return datetime.min.replace(tzinfo=KYIV)
        return parsed.astimezone(KYIV)

    def rollover_inbox_day(self, *, now: datetime | None = None) -> dict[str, int]:
        """Apply the current-day Inbox boundary without deleting historical data.

        Only unqueued ``new``/``draft`` blocks may be split. Rejected all-old
        blocks retain the legacy archive behavior, while approved/queued material
        is left untouched and remains reachable from Queue/History.
        """
        current = (now or datetime.now(KYIV)).astimezone(KYIV)
        archived_groups = 0
        trimmed_groups: list[int] = []
        archived_articles = 0

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                group_rows = db.execute(
                    """
                    SELECT g.id,g.status,g.canonical_title
                    FROM news_groups g
                    WHERE g.status IN ('new','draft','rejected')
                      AND NOT EXISTS (
                          SELECT 1 FROM publication_batches b
                          JOIN articles qa ON qa.id=b.article_id
                          WHERE qa.group_id=g.id
                      )
                    ORDER BY g.id
                    """
                ).fetchall()

                for group_row in group_rows:
                    group_id = int(group_row["id"])
                    status = str(group_row["status"])
                    article_rows = db.execute(
                        """
                        SELECT id,title,published_at,discovered_at
                        FROM articles
                        WHERE group_id=?
                        ORDER BY COALESCE(published_at,discovered_at),id
                        """,
                        (group_id,),
                    ).fetchall()
                    if not article_rows:
                        continue

                    today_rows = [
                        row
                        for row in article_rows
                        if self._article_is_today(
                            row["published_at"], row["discovered_at"], now=current
                        )
                    ]
                    stale_rows = [row for row in article_rows if row not in today_rows]

                    if not today_rows:
                        changed = db.execute(
                            "UPDATE news_groups SET status='archived',updated_at=? WHERE id=? AND status!='archived'",
                            (_iso(), group_id),
                        ).rowcount
                        db.execute("UPDATE articles SET status='archived' WHERE group_id=?", (group_id,))
                        if changed:
                            archived_groups += 1
                            archived_articles += len(article_rows)
                        continue

                    # Rejected blocks are already outside the working Inbox. Do not
                    # rewrite their group identity because content-exclusion audit rows
                    # may intentionally point at that original group.
                    if not stale_rows or status not in {"new", "draft"}:
                        continue

                    stale_newest = max(stale_rows, key=self._article_sort_key)
                    stale_title = str(stale_newest["title"] or "Без заголовка").strip() or "Без заголовка"
                    now_iso = _iso()
                    cursor = db.execute(
                        """
                        INSERT INTO news_groups(canonical_title,status,created_at,updated_at)
                        VALUES(?,'archived',?,?)
                        """,
                        (stale_title, now_iso, now_iso),
                    )
                    archive_group_id = int(cursor.lastrowid)
                    stale_ids = [int(row["id"]) for row in stale_rows]
                    placeholders = ",".join("?" for _ in stale_ids)
                    db.execute(
                        f"UPDATE articles SET group_id=?,status='archived' WHERE id IN ({placeholders})",
                        [archive_group_id, *stale_ids],
                    )

                    current_titles = {
                        str(row["title"] or "").strip()
                        for row in today_rows
                        if str(row["title"] or "").strip()
                    }
                    canonical = str(group_row["canonical_title"] or "").strip()
                    if canonical not in current_titles:
                        newest = max(today_rows, key=self._article_sort_key)
                        canonical = str(newest["title"] or "Без заголовка").strip() or "Без заголовка"

                    # The evidence set changed, so any generated/manual draft derived
                    # from the mixed old+new block is no longer trustworthy. Keep media
                    # and publication options, but force a fresh editorial pass.
                    db.execute(
                        """
                        UPDATE news_groups
                        SET canonical_title=?,status='new',headline='',fact_card='',rewrite_text='',ai_draft_text='',
                            platform_texts_json='{}',explosiveness_score=0,explosiveness_confidence=0,
                            explosiveness_details_json='{}',recommended_platforms_json='[]',updated_at=?
                        WHERE id=?
                        """,
                        (canonical, now_iso, group_id),
                    )
                    today_ids = [int(row["id"]) for row in today_rows]
                    today_placeholders = ",".join("?" for _ in today_ids)
                    db.execute(
                        f"""
                        UPDATE articles
                        SET status='new',headline='',fact_card='',rewrite_text='',platform_texts_json='{{}}'
                        WHERE id IN ({today_placeholders})
                        """,
                        today_ids,
                    )
                    trimmed_groups.append(group_id)
                    archived_articles += len(stale_rows)

                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

        # Re-score only blocks whose evidence membership changed. This is done
        # outside the write transaction to keep the midnight lock short.
        for group_id in trimmed_groups:
            group = self.get_group(group_id)
            score, confidence, details, recommendations = calculate_explosiveness(group, None)
            self.set_group_analysis(
                group_id,
                score=score,
                confidence=confidence,
                details=details,
                recommendations=recommendations,
            )

        return {
            "archived_groups": archived_groups,
            "trimmed_groups": len(trimmed_groups),
            "archived_articles": archived_articles,
        }

    def archive_stale_groups(self) -> int:
        """Compatibility entrypoint used by startup; now performs full RC18 rollover."""
        result = self.rollover_inbox_day()
        return int(result["archived_groups"]) + int(result["trimmed_groups"])

    def list_groups(self, status: str | None = None, limit: int = 200):
        """Hide previous-day material from every working Inbox view immediately.

        Archive remains historical by design. Current-day filtering is also useful
        during the few seconds while the midnight split/archive worker is running.
        """
        requested = max(1, int(limit))
        if status == "archived":
            return super().list_groups(status=status, limit=requested)

        # Pull a wider bounded window before the date filter so yesterday's recent
        # approved rows cannot crowd today's smaller Inbox out of the requested page.
        scan_limit = min(20000, max(requested * 5, 1000))
        groups = super().list_groups(status=status, limit=scan_limit)
        current = datetime.now(KYIV)
        filtered = [
            group
            for group in groups
            if is_today_kyiv(group.last_published_at, now=current)
        ]
        return filtered[:requested]
