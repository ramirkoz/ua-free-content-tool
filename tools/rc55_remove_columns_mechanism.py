from pathlib import Path

p = Path("content_agent/v2/ui/window.py")
s = p.read_text(encoding="utf-8")
s = s.replace("        self._install_v2_inbox_reset_button()\n", "")
start = s.find("    def _install_v2_inbox_reset_button(self) -> None:\n")
end = s.find("    @staticmethod\n    def _v2_time_only", start)
if start < 0 or end < 0:
    raise SystemExit("legacy column-reset block not found")
s = s[:start] + s[end:]
p.write_text(s, encoding="utf-8")
print("Removed active legacy Inbox column-reset mechanism")
