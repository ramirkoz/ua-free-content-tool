from pathlib import Path

p = Path("content_agent/ui/main_window.py")
s = p.read_text(encoding="utf-8")
old = "                items = collect_source(source)\n                total += self.db.insert_collected(int(source.id), items)"
new = "                collection = getattr(getattr(self, 'services', None), 'collection', None)\n                items = collection.collect(source) if collection is not None else collect_source(source)\n                total += self.db.insert_collected(int(source.id), items)"
count = s.count(old)
if count < 1:
    raise SystemExit("active collect_source block not found")
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")
print(f"wired CollectionService into {count} active collection path(s)")
