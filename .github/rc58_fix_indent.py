from pathlib import Path

p = Path('content_agent/v2/ui/manual_topics_window_rc44.py')
text = p.read_text(encoding='utf-8')
old = '''                if progress is not None:\n                    def _stop_media_progress() -> None:\n                    progress.stop()\n                    progress.grid_remove()\n                self._post_ui(_stop_media_progress)\n'''
new = '''                if progress is not None:\n                    def _stop_media_progress() -> None:\n                        progress.stop()\n                        progress.grid_remove()\n                    self._post_ui(_stop_media_progress)\n'''
if old not in text:
    raise SystemExit('RC58 progress indentation marker not found')
p.write_text(text.replace(old, new), encoding='utf-8')
