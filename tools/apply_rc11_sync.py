from pathlib import Path

ROOT = Path('.')


def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def write(path, text):
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(path, old, new):
    text = read(path)
    if new in text and old not in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: expected one match, found {text.count(old)} for {old[:80]!r}')
    write(path, text.replace(old, new, 1))


write('VERSION.txt', '1.3.1-rc11\n')
write('PUBLIC_VERSION.txt', '1.3.1-rc11\n')
write('content_agent/__init__.py', '"""UA FREE Content Tool."""\n\n__version__ = "1.3.1-rc11"\n')

replace_once('content_agent/ai_task_profiles.py',
'''    cloud_timeout_seconds=28,\n    local_timeout_seconds=45,\n    task_timeout_seconds=70,\n''',
'''    cloud_timeout_seconds=45,\n    local_timeout_seconds=18,\n    task_timeout_seconds=82,\n''')

replace_once('content_agent/ai_router_v1_2_2.py',
'''    ordered_slots = [*primary, *local_slots, *secondary]\n''',
'''    # Try every configured cloud provider before spending the remaining budget\n    # on local inference. A stalled local runtime must never starve a healthy\n    # secondary cloud model.\n    ordered_slots = [*primary, *secondary, *local_slots]\n''')
replace_once('content_agent/ai_router_v1_2_2.py',
'''        local_reserve = min(local_timeout, max(8, min(22, total_budget // 3)))\n''',
'''        local_reserve = min(local_timeout, max(6, min(10, total_budget // 5)))\n''')
replace_once('content_agent/ai_router_v1_2_2.py',
'''        if slot.provider != "local":\n            if legacy._cooldown_active(state, legacy._provider_key(slot.provider), now) or legacy._cooldown_active(\n                state, legacy._slot_key(slot), now\n            ):\n                continue\n''',
'''        provider_cooldown = False\n        if slot.provider != "local":\n            provider_cooldown = legacy._cooldown_active(state, legacy._provider_key(slot.provider), now)\n        model_cooldown = legacy._cooldown_active(state, legacy._slot_key(slot), now)\n        if provider_cooldown or model_cooldown:\n            continue\n''')
replace_once('content_agent/ai_router_v1_2_2.py',
'''                provider_cap = min(cloud_timeout, 28 if slot.provider == "codex" else 9)\n''',
'''                provider_caps = {"codex": 42, "groq": 12, "nvidia": 10, "gemini": 10, "cloudflare": 10}\n                provider_cap = min(cloud_timeout, provider_caps.get(slot.provider, 10))\n''')
replace_once('content_agent/ai_router_v1_2_2.py',
'''            if slot.provider != "local":\n                key_name = (\n                    legacy._provider_key(slot.provider)\n                    if exc.kind in {"auth", "configuration"}\n                    else legacy._slot_key(slot)\n                )\n                cooldown = legacy._cooldown_seconds(exc)\n                if slot.provider == "codex" and exc.kind == "quota":\n                    cooldown = min(cooldown, 5 * 60)\n                legacy._put_cooldown(state, key_name, cooldown, str(exc))\n                legacy.save_router_state(state)\n''',
'''            key_name = (\n                legacy._provider_key(slot.provider)\n                if slot.provider != "local" and exc.kind in {"auth", "configuration"}\n                else legacy._slot_key(slot)\n            )\n            cooldown = legacy._cooldown_seconds(exc)\n            if slot.provider == "codex" and exc.kind == "quota":\n                cooldown = min(cooldown, 5 * 60)\n            if slot.provider == "local":\n                # A dead/stalled local runtime used to eat the timeout on every\n                # rewrite. Back it off briefly and let working cloud providers\n                # handle the next request.\n                cooldown = 300 if exc.kind in {"configuration", "auth"} else 90\n            legacy._put_cooldown(state, key_name, cooldown, str(exc))\n            legacy.save_router_state(state)\n''')

replace_once('content_agent/rowboat_bridge_v1_3.py',
'''def sync_editorial_memory(database) -> dict[str, int]:\n''',
'''def _write_text_if_changed(path: Path, text: str) -> None:\n    try:\n        if path.exists() and path.read_text(encoding="utf-8") == text:\n            return\n    except OSError:\n        pass\n    path.write_text(text, encoding="utf-8")\n\n\ndef sync_editorial_memory(database) -> dict[str, int]:\n''')
replace_once('content_agent/rowboat_bridge_v1_3.py',
'''        (examples_dir / f"example-{item_id}.md").write_text(\n            "---\\ntype: editorial-example\\nlanguage: uk\\n---\\n\\n"\n            f"# {headline or 'Схвалений рерайт'}\\n\\n## Джерело\\n\\n{source_text}\\n\\n"\n            f"## Фінальний текст\\n\\n{final_text}\\n\\nЗв'язки: [[UA FREE Editorial Memory]]\\n",\n            encoding="utf-8",\n        )\n''',
'''        example_text = (\n            "---\\ntype: editorial-example\\nlanguage: uk\\n---\\n\\n"\n            f"# {headline or 'Схвалений рерайт'}\\n\\n## Джерело\\n\\n{source_text}\\n\\n"\n            f"## Фінальний текст\\n\\n{final_text}\\n\\nЗв'язки: [[UA FREE Editorial Memory]]\\n"\n        )\n        _write_text_if_changed(examples_dir / f"example-{item_id}.md", example_text)\n''')
replace_once('content_agent/rowboat_bridge_v1_3.py',
'''        (decisions_dir / f"decision-{fingerprint}.md").write_text(\n            "---\\ntype: topic-decision\\n"\n            f"decision: {decision}\\n---\\n\\n# Редакційне рішення: {decision}\\n\\n"\n            f"## Матеріал A\\n\\n{anchor}\\n\\n## Матеріал B\\n\\n{candidate}\\n\\n"\n            "Зв'язки: [[UA FREE Editorial Memory]]\\n",\n            encoding="utf-8",\n        )\n''',
'''        decision_text = (\n            "---\\ntype: topic-decision\\n"\n            f"decision: {decision}\\n---\\n\\n# Редакційне рішення: {decision}\\n\\n"\n            f"## Матеріал A\\n\\n{anchor}\\n\\n## Матеріал B\\n\\n{candidate}\\n\\n"\n            "Зв'язки: [[UA FREE Editorial Memory]]\\n"\n        )\n        _write_text_if_changed(decisions_dir / f"decision-{fingerprint}.md", decision_text)\n''')

# UI base: freeze diagnostics and avoid pointless 0-item Inbox rebuilds.
replace_once('content_agent/ui/main_window.py', 'import queue\nimport threading\n', 'import faulthandler\nimport queue\nimport threading\nimport time\n')
replace_once('content_agent/ui/main_window.py',
'''        self._ui_event_queue: queue.Queue[Callable[[], None]] = queue.Queue()\n        self._ui_dispatch_after_id: str | None = None\n''',
'''        self._ui_event_queue: queue.Queue[Callable[[], None]] = queue.Queue()\n        self._ui_dispatch_after_id: str | None = None\n        self._ui_last_pulse = time.monotonic()\n        self._ui_last_freeze_dump = 0.0\n''')
replace_once('content_agent/ui/main_window.py',
'''        self.root.protocol("WM_DELETE_WINDOW", self.close)\n        self._ui_dispatch_after_id = self.root.after(50, self._drain_ui_events)\n''',
'''        self.root.protocol("WM_DELETE_WINDOW", self.close)\n        self._ui_dispatch_after_id = self.root.after(50, self._drain_ui_events)\n        threading.Thread(target=self._ui_freeze_watchdog_loop, name="ui-freeze-watchdog", daemon=True).start()\n''')
replace_once('content_agent/ui/main_window.py',
'''        self._ui_dispatch_after_id = None\n        if getattr(self, "_closing", False):\n''',
'''        self._ui_dispatch_after_id = None\n        self._ui_last_pulse = time.monotonic()\n        if getattr(self, "_closing", False):\n''')
replace_once('content_agent/ui/main_window.py',
'''    def _start_background_services(self) -> None:\n''',
'''    def _ui_freeze_watchdog_loop(self) -> None:\n        """Persist a Python stack dump if Tk stops pumping events for too long."""\n        while not self.stop_event.wait(2.0):\n            lag = time.monotonic() - self._ui_last_pulse\n            if lag < 8.0:\n                continue\n            now = time.monotonic()\n            if now - self._ui_last_freeze_dump < 30.0:\n                continue\n            self._ui_last_freeze_dump = now\n            try:\n                path = data_dir() / "ui_freeze_trace.log"\n                with path.open("a", encoding="utf-8") as handle:\n                    handle.write(f"\\n=== UI FREEZE {datetime.now().isoformat(timespec='seconds')} lag={lag:.1f}s ===\\n")\n                    handle.flush()\n                    faulthandler.dump_traceback(file=handle, all_threads=True)\n            except Exception:\n                pass\n\n    def _start_background_services(self) -> None:\n''')
replace_once('content_agent/ui/main_window.py',
'''        self.refresh_sources()\n        self.refresh_groups()\n        self._notify_current_group_updates()\n''',
'''        self.refresh_sources()\n        if int(total or 0) > 0:\n            self.refresh_groups()\n            self._notify_current_group_updates()\n''')

# RC11 editor overlap guard and lighter rewrite completion path.
for old, new in [
    ('UA FREE Content Tool v1.3.1-rc10 stabilization layer.', 'UA FREE Content Tool v1.3.1-rc11 stabilization layer.'),
    ('VERSION_LABEL = "1.3.1-rc10"', 'VERSION_LABEL = "1.3.1-rc11"'),
    ('self.root.title("UA FREE Content Tool — v1.3.1-rc10")', 'self.root.title("UA FREE Content Tool — v1.3.1-rc11")'),
]:
    replace_once('content_agent/ui/v1_3_window.py', old, new)
replace_once('content_agent/ui/v1_3_window.py',
'''        self._rewrite_attempt_serial = 0\n''',
'''        self._rewrite_attempt_serial = 0\n        self._rewrite_inflight = threading.Event()\n''')
replace_once('content_agent/ui/v1_3_window.py',
'''        self.db.set_group_options(\n''',
'''        if self._rewrite_inflight.is_set():\n            self.msg.showinfo(\n                "AI-рерайт ще завершується",\n                "Попередній AI-рерайт ще зупиняє фоновий виклик. Зачекайте кілька секунд; паралельний другий рерайт не запускається.",\n                parent=self.root,\n            )\n            return\n\n        self.db.set_group_options(\n''')
replace_once('content_agent/ui/v1_3_window.py',
'''        logger.info("RC8 rewrite attempt=%s group=%s started", attempt_id, group.id)\n\n        def action() -> object:\n''',
'''        logger.info("RC8 rewrite attempt=%s group=%s started", attempt_id, group.id)\n        self._rewrite_inflight.set()\n\n        def action() -> object:\n''')
replace_once('content_agent/ui/v1_3_window.py',
'''            try:\n                sync_editorial_memory(self.db)\n                examples = rank_editorial_examples(\n''',
'''            try:\n                # Do not export the entire Rowboat memory graph on every rewrite.\n                # The live DB examples below are authoritative; Rowboat has its own\n                # explicit synchronization action in Settings. Rewriting thousands\n                # of memory files here was pure I/O tax and could outlive the UI timeout.\n                examples = rank_editorial_examples(\n''')
replace_once('content_agent/ui/v1_3_window.py',
'''            except Exception:\n                logger.exception("RC8 rewrite attempt=%s group=%s failed", attempt_id, group.id)\n                raise\n\n        def success(result: object) -> None:\n''',
'''            except Exception:\n                logger.exception("RC8 rewrite attempt=%s group=%s failed", attempt_id, group.id)\n                raise\n            finally:\n                self._rewrite_inflight.clear()\n\n        def success(result: object) -> None:\n''')
replace_once('content_agent/ui/v1_3_window.py', '            self.refresh_groups()\n            self.update_text_metrics()\n', '            self.update_text_metrics()\n')

# Public docs.
readme = read('README.md')
readme = readme.replace('v1.3.1-rc10', 'v1.3.1-rc11')
write('README.md', readme)

notes = '''# UA FREE Content Tool v1.3.1-rc11\n\nRC11 is a focused stability candidate over RC10.\n\n## Rewrite reliability\n- Prevents a second rewrite from starting while the previous timed-out worker is still shutting down.\n- Codex gets a realistic bounded window for rewrite-sized prompts instead of being killed too early.\n- Cloud fallbacks are exhausted before local inference.\n- A stalled local runtime now receives a short cooldown instead of consuming the timeout on every click.\n- Local rewrite fallback timeout is reduced; the total rewrite budget stays bounded.\n- Full Rowboat memory export is no longer performed on every rewrite click; DB examples remain live and Rowboat can be synchronized explicitly.\n- Rowboat synchronization writes only changed memory files.\n\n## UI freeze mitigation\n- Automatic 5-minute collection no longer rebuilds the full Inbox when zero new materials were collected.\n- Successful rewrite no longer rebuilds the entire Inbox unnecessarily.\n- Added a lightweight UI heartbeat watchdog. If Tk stops pumping events for 8+ seconds, `Data/ui_freeze_trace.log` receives all Python thread stacks for exact diagnosis.\n\n## Compatibility\n- No database schema change.\n- Existing `Data` from RC10 is compatible.\n- RC10 Inbox column layout is preserved.\n'''
write('RELEASE_NOTES_v1.3.1-rc11.md', notes)

print('RC11_SYNC_PATCH_OK')
