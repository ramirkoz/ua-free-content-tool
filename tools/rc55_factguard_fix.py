from pathlib import Path

p = Path("content_agent/fact_guard.py")
s = p.read_text(encoding="utf-8")
lines = s.splitlines()
changed = False

# Keep the canonical numeric matcher able to read grouped thousands and decimals.
for i, line in enumerate(lines):
    if 'r"(?P<number>' in line:
        replacement = r'''    r"(?P<number>(?:\d{1,3}(?:[ \u00a0\u202f,'’ʼ]\d{3})+|\d+(?:[.,]\d+)?))"'''
        if lines[i] != replacement:
            lines[i] = replacement
            changed = True
        break
else:
    raise SystemExit("_NUMBER_RE number line not found")

# RC55 regression: the Russian abbreviation "долл." was accidentally encoded
# with a doubled regex backslash, so the source amount lost its USD unit while
# the Ukrainian rewrite kept it. Repair both suffix and canonical currency regexes.
for i, line in enumerate(lines):
    if "дол(?:л?" in line and r"\\." in line:
        lines[i] = line.replace(r"\\.", r"\.")
        changed = True

# Capitalized Latin product/model tokens such as Cybercab/Cybertruck must remain
# fail-closed. Ordinary short title-case words are still ignored to avoid noise.
marker = "if simple_title and len(clean) >= 6:"
if marker not in lines:
    for i, line in enumerate(lines):
        if "simple_title = clean[:1].isupper() and clean[1:].islower()" in line:
            lines[i + 1:i + 1] = [
                "    if simple_title and len(clean) >= 6:",
                "        return True",
            ]
            changed = True
            break
    else:
        raise SystemExit("simple_title decision line not found")

if changed:
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Fact Guard numeric/currency/entity strictness repaired")
else:
    print("Fact Guard already repaired")
