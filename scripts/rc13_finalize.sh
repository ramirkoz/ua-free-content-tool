#!/usr/bin/env bash
set -euo pipefail

git apply --ignore-space-change --ignore-whitespace .rc13-core.patch

python - <<'PY'
from pathlib import Path

p = Path('content_agent/ui/queue_safety_v1_3_1_rc1.py')
s = p.read_text(encoding='utf-8')
old = 'self.worker.request_cancel(batch.id)'
new = 'self.worker.request_cancel(batch.id, reason="queue-ui-confirmed")'
if old not in s:
    raise SystemExit('queue safety RC12 call not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

p = Path('content_agent/ui/v1_3_window.py')
s = p.read_text(encoding='utf-8')
if '1.3.1-rc12' not in s:
    raise SystemExit('v1_3_window RC12 version not found')
p.write_text(s.replace('1.3.1-rc12', '1.3.1-rc13'), encoding='utf-8')

p = Path('tests/test_r8_fix8.py')
s = p.read_text(encoding='utf-8')
old = 'monkeypatch.setattr("content_agent.google_drive.probe_public_media", lambda _file_id: (True, "image/jpeg"))'
new = 'probes = iter([(False, ""), (True, "image/jpeg")])\n    monkeypatch.setattr("content_agent.google_drive.probe_public_media", lambda _file_id: next(probes))'
if old not in s:
    raise SystemExit('RC12 Threads probe test line not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
PY

rm -f .rc13-core.patch \
  .github/workflows/rc13-sync.yml \
  .github/workflows/rc13-sync2.yml \
  .github/workflows/rc13-canonical-sync.yml \
  .github/workflows/rc13-finalize.yml \
  .github/workflows/rc13-final-helper.yml \
  scripts/rc13_finalize.sh

python -m compileall -q content_agent tests app.py
python -m pytest -q tests/test_rc13_publication_stability.py tests/test_r8_fix8.py tests/test_rc12_stability.py

test "$(cat VERSION.txt)" = "1.3.1-rc13"
test "$(cat PUBLIC_VERSION.txt)" = "1.3.1-rc13"
python -c "from content_agent import __version__; assert __version__ == '1.3.1-rc13'"

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git add -A
git commit -m 'Release v1.3.1-rc13 publication stabilization'
git push origin HEAD:main

gh workflow run release.yml --ref main
