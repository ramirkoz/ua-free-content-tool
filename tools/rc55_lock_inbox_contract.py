from pathlib import Path

p = Path("content_agent/v2/ui/window.py")
s = p.read_text(encoding="utf-8")
old = 'desired = tuple(item for item in ("id", "status", "title", "topic", "sources", "published", "score", "history") if item in columns)'
new = 'desired = tuple(item for item in ("title", "topic", "sources", "published") if item in columns)'
if old not in s:
    raise SystemExit("old V2 Inbox display contract not found")
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print("V2 Inbox display contract locked to four operator columns")
