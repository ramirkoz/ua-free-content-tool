from __future__ import annotations

import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import content_agent
from content_agent.fact_guard import extract_numbers, guard_rewrite
from content_agent.services.collection import CollectionService
from content_agent.v2.supervisor.update_manifest import MANIFEST_SCHEMA, canonical_manifest_bytes, verify_manifest
from content_agent.v2.ui.tabs.inbox import InboxTabController


def test_rc55_version_alignment() -> None:
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    assert Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip() == version
    assert content_agent.__version__ == version
    assert version.startswith("2.0.0-rc")
    assert int(version.rsplit("rc", 1)[1]) >= 55


def test_rc55_fact_guard_numeric_extraction_is_live() -> None:
    assert extract_numbers("25 моделей") == {"25"}
    assert extract_numbers("500 тыс.") == {"500000"}
    result = guard_rewrite("Перевірили 25 моделей.", "Тест", "Перевірили 26 моделей.")
    assert result.allowed is False
    assert "26" in result.unsupported_numbers


def test_rc55_inbox_contract_has_only_four_operator_columns() -> None:
    assert InboxTabController.DISPLAY_COLUMNS == ("title", "topic", "sources", "published")
    shell = Path("content_agent/v2/ui/manual_topics_window_rc44.py").read_text(encoding="utf-8")
    v2_window = Path("content_agent/v2/ui/window.py").read_text(encoding="utf-8")
    legacy = Path("content_agent/v2/ui/legacy_manual_topics_window_rc44.py").read_text(encoding="utf-8")
    assert 'tree.configure(displaycolumns=("title", "topic", "sources", "published"))' in shell
    assert '"Пошук у Вхідних:"' in shell and '"Колонки"' in shell
    assert "widget.destroy()" in shell
    assert "_install_v2_inbox_reset_button" not in v2_window
    assert "reset_v2_inbox_columns" not in v2_window
    assert '"Відновити стандартні колонки": "Колонки"' not in legacy
    cleanup = shell.split("if text in {", 1)[1].split("}:", 1)[0]
    assert "Склад блоку" not in cleanup


def test_rc55_collection_service_is_composed_and_active_path_uses_it() -> None:
    container = Path("content_agent/app/container.py").read_text(encoding="utf-8")
    window = Path("content_agent/ui/main_window.py").read_text(encoding="utf-8")
    assert "collection: CollectionService" in container
    assert "collection=CollectionService()" in container
    assert "collection.collect(source)" in window
    assert CollectionService is not None


def test_rc55_codex_runtime_is_hash_locked() -> None:
    source = Path("content_agent/codex_engine_v1_4_rc28.py").read_text(encoding="utf-8")
    assert "6a11313e86027dd2da00f1af475388a578a19076ae8150b0f1c305d8564c973f" in source
    assert "81ab68fdadf448af52736282619875e10d365d93dd7442e94925899e77b99e7d" in source
    assert "_verify_locked_download(download_dir)" in source
    assert '"--no-index"' in source


def test_rc55_update_manifest_ed25519_accepts_valid_and_rejects_tamper() -> None:
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_raw).decode("ascii")
    payload = {
        "schema": MANIFEST_SCHEMA,
        "version": "2.0.0-rc55",
        "asset_name": "UA_FREE_Content_Tool_v2.0.0-rc55_Windows_Portable.zip",
        "sha256": "a" * 64,
        "min_updater_version": 1,
        "rollback": {"supported": True},
    }
    signature = base64.b64encode(private.sign(canonical_manifest_bytes(payload))).decode("ascii")
    verified = verify_manifest(payload, signature, public_key_b64=public_b64)
    assert verified.version == "2.0.0-rc55"
    tampered = dict(payload)
    tampered["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="SIGNATURE"):
        verify_manifest(tampered, signature, public_key_b64=public_b64)


def test_rc55_updater_requires_signed_manifest_and_rollback() -> None:
    source = Path("content_agent/v2/supervisor/updater.py").read_text(encoding="utf-8")
    assert "UPDATE_SIGNED_MANIFEST_MISSING" in source
    assert "verify_manifest(manifest_payload, signature_b64)" in source
    assert "verified.sha256" in source
    manifest = Path("content_agent/v2/supervisor/update_manifest.py").read_text(encoding="utf-8")
    assert "UPDATE_MANIFEST_ROLLBACK_REQUIRED" in manifest
    assert "Ed25519PublicKey" in manifest


def test_rc55_no_new_numbered_window_layer_or_direct_router_runtime() -> None:
    assert not list(Path("content_agent").rglob("*rc55*window*.py"))
    assert not Path("content_agent/v2/ai/direct_router_runtime.py").exists()
