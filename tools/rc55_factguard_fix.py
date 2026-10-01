from pathlib import Path

p = Path("content_agent/fact_guard.py")
s = p.read_text(encoding="utf-8")
lines = s.splitlines()
changed = False

for i, line in enumerate(lines):
    if 'r"(?P<number>' in line:
        replacement = r'''    r"(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f,'’ʼ]\d{3})+|\d+(?:[.,]\d+)?))"'''
        if lines[i] != replacement:
            lines[i] = replacement
            changed = True
        break
else:
    raise SystemExit("_NUMBER_RE number line not found")

for i, line in enumerate(lines):
    if "дол(?:л?" in line and r"\\." in line:
        lines[i] = line.replace(r"\\.", r"\.")
        changed = True

# A plain sentence-start English word ("Destroy", "Keep") is not an entity.
# A long TitleCase token in factual position inside a sentence (Cybercab,
# Cybertruck, Windows) is model/name-like and must remain fail-closed.
for i in range(len(lines) - 1):
    if lines[i].strip() == "if simple_title and len(clean) >= 6:" and lines[i + 1].strip() == "return True":
        del lines[i:i + 2]
        changed = True
        break

helper = "def _is_contextual_title_entity(text: str, start: int, token: str) -> bool:"
if not any(line.startswith(helper) for line in lines):
    insert_at = next(i for i, line in enumerate(lines) if line.startswith("def _parse_decimal"))
    block = [
        "def _is_contextual_title_entity(text: str, start: int, token: str) -> bool:",
        "    clean = str(token or \"\").strip(\".,:;!?()[]{}«»\\\"'\")",
        "    if len(clean) < 6 or not (clean[:1].isupper() and clean[1:].islower()):",
        "        return False",
        "    prefix = str(text or \"\")[:max(0, int(start))].rstrip()",
        "    if not prefix:",
        "        return False",
        "    return prefix[-1] not in \".!?…\"",
        "",
        "",
    ]
    lines[insert_at:insert_at] = block
    changed = True

old = [
    "    for token in _LATIN_TOKEN_RE.findall(text):",
    "        if _is_strong_latin_token(token):",
    "            result.add(token.casefold())",
]
new = [
    "    for match in _LATIN_TOKEN_RE.finditer(text):",
    "        token = match.group(0)",
    "        if _is_strong_latin_token(token) or _is_contextual_title_entity(text, match.start(), token):",
    "            result.add(token.casefold())",
]
for i in range(len(lines) - len(old) + 1):
    if lines[i:i + len(old)] == old:
        lines[i:i + len(old)] = new
        changed = True
        break
if old[0] in lines and not any("_is_contextual_title_entity(text, match.start(), token)" in line for line in lines):
    raise SystemExit("extract_latin_entities block not replaced")

if changed:
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Fact Guard contextual entity strictness repaired")
else:
    print("Fact Guard already repaired")
