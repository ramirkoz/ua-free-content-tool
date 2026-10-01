from pathlib import Path

p = Path("content_agent/fact_guard.py")
s = p.read_text(encoding="utf-8")
lines = s.splitlines()
changed = False
for i, line in enumerate(lines):
    if 'r"(?P<number>' in line:
        lines[i] = r'''    r"(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f,'’ʼ]\d{3})+|\d+(?:[.,]\d+)?))"'''
        changed = True
        break
if not changed:
    raise SystemExit("_NUMBER_RE number line not found")
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Fact Guard numeric regex repaired")
