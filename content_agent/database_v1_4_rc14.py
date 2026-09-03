from __future__ import annotations

import re
from typing import Iterable

from .database import _iso
from .database_v1_4_rc11 import Database as Rc11Database
from .news_logic import calculate_explosiveness


class Database(Rc11Database):
    """RC14 Inbox composition tools without a schema migration.

    Keyword search is deliberately deterministic and local. Article detaching is
    the inverse of a pre-publication merge: the selected source stories are moved
    into new one-story blocks rather than deleted from Data.
    """

    @staticmethod
    def _keyword_terms(value: str) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[\w’'\-+.#]+", str(value or "").casefold(), flags=re.UNICODE):
            clean = token.strip("_'’-+.#")
            if clean and clean not in terms:
                terms.append(clean)
        return terms

    def search_inbox_groups(self, keywords: str, *, limit: int = 1000):
        """Find merge-eligible Inbox blocks whose title/body contains every term.

        Matching uses Python casefold instead of SQLite NOCASE so Ukrainian and
        other Unicode text behave correctly. A term may occur in the canonical
        title, any source title, or any source body inside the block.
        """
        terms = self._keyword_terms(keywords)
        if not terms:
            return []
        matches = []
        for group in self.list_groups_with_articles(status=None, limit=20000):
            if group.status not in {"new", "draft"}:
                continue
            parts = [group.canonical_title]
            for article in group.articles:
                parts.extend((article.title, article.raw_text))
            haystack = "\n".join(str(part or "") for part in parts).casefold()
            if all(term in haystack for term in terms):
                matches.append(group)
                if len(matches) >= max(1, int(limit)):
                    break
        return matches

    def detach_articles_from_group(self, group_id: int, article_ids: Iterable[int]) -> list[int]:
        """Return selected articles from a merged block to Inbox as separate blocks.

        Nothing is deleted. The operation is available only before publication
        history/queue exists. At least one article must remain in the original
        block, whose derived editorial text/analysis is invalidated and rebuilt.
        """
        group_id = int(group_id)
        ordered: list[int] = []
        for raw in article_ids:
            article_id = int(raw)
            if article_id > 0 and article_id not in ordered:
                ordered.append(article_id)
        if not ordered:
            raise ValueError("Оберіть хоча б одну новину для вилучення з блоку.")

        created_group_ids: list[int] = []
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                group_row = db.execute(
                    "SELECT id,status,canonical_title FROM news_groups WHERE id=?",
                    (group_id,),
                ).fetchone()
                if group_row is None:
                    raise KeyError(group_id)
                if str(group_row["status"]) not in {"new", "draft"}:
                    raise ValueError(
                        "Склад можна змінювати лише у новому або чернетковому блоці до публікації."
                    )

                queued = db.execute(
                    """
                    SELECT 1 FROM publication_batches b
                    JOIN articles a ON a.id=b.article_id
                    WHERE a.group_id=? LIMIT 1
                    """,
                    (group_id,),
                ).fetchone()
                if queued is not None:
                    raise ValueError(
                        "Не можна змінювати склад блоку, для якого вже існує черга або історія публікації."
                    )

                all_rows = db.execute(
                    """
                    SELECT a.id,a.title,a.published_at,a.discovered_at
                    FROM articles a WHERE a.group_id=? ORDER BY a.id
                    """,
                    (group_id,),
                ).fetchall()
                if len(all_rows) < 2:
                    raise ValueError("У цьому блоці лише одна новина: вилучати нічого.")
                by_id = {int(row["id"]): row for row in all_rows}
                missing = [article_id for article_id in ordered if article_id not in by_id]
                if missing:
                    raise ValueError("Одна з вибраних новин більше не належить цьому блоку.")
                if len(ordered) >= len(all_rows):
                    raise ValueError("У початковому блоці має залишитися хоча б одна новина.")

                now = _iso()
                for article_id in ordered:
                    article = by_id[article_id]
                    title = str(article["title"] or "Без заголовка").strip() or "Без заголовка"
                    cursor = db.execute(
                        "INSERT INTO news_groups(canonical_title,created_at,updated_at) VALUES(?,?,?)",
                        (title, now, now),
                    )
                    new_group_id = int(cursor.lastrowid)
                    created_group_ids.append(new_group_id)
                    db.execute(
                        """
                        UPDATE articles
                        SET group_id=?,status='new',headline='',fact_card='',rewrite_text='',platform_texts_json='{}'
                        WHERE id=? AND group_id=?
                        """,
                        (new_group_id, article_id, group_id),
                    )

                remaining = db.execute(
                    """
                    SELECT id,title FROM articles WHERE group_id=?
                    ORDER BY COALESCE(published_at,discovered_at) DESC,id DESC
                    """,
                    (group_id,),
                ).fetchall()
                if not remaining:
                    raise RuntimeError("Після вилучення блок несподівано залишився без новин.")
                canonical = str(group_row["canonical_title"] or "").strip()
                remaining_titles = {str(row["title"] or "").strip() for row in remaining}
                if canonical not in remaining_titles:
                    canonical = str(remaining[0]["title"] or "Без заголовка").strip() or "Без заголовка"

                db.execute(
                    """
                    UPDATE news_groups
                    SET canonical_title=?,status='new',headline='',fact_card='',rewrite_text='',ai_draft_text='',
                        platform_texts_json='{}',explosiveness_score=0,explosiveness_confidence=0,
                        explosiveness_details_json='{}',recommended_platforms_json='[]',updated_at=?
                    WHERE id=?
                    """,
                    (canonical, now, group_id),
                )
                db.execute(
                    """
                    UPDATE articles
                    SET status='new',headline='',fact_card='',rewrite_text='',platform_texts_json='{}'
                    WHERE group_id=?
                    """,
                    (group_id,),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

        for affected_id in [group_id, *created_group_ids]:
            group = self.get_group(affected_id)
            score, confidence, details, recommendations = calculate_explosiveness(group, None)
            self.set_group_analysis(
                affected_id,
                score=score,
                confidence=confidence,
                details=details,
                recommendations=recommendations,
            )
        return created_group_ids
