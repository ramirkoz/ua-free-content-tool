from pathlib import Path

# RC54 feature test must survive RC55 while still enforcing version alignment.
p = Path("tests/test_rc54_operator_ui_retention.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
'''    assert Path("VERSION.txt").read_text(encoding="utf-8").strip() == "2.0.0-rc54"\n    assert Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip() == "2.0.0-rc54"''',
'''    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()\n    public = Path("PUBLIC_VERSION.txt").read_text(encoding="utf-8").strip()\n    assert version == public\n    assert version.startswith("2.0.0-rc") and int(version.rsplit("rc", 1)[1]) >= 54''')
p.write_text(s, encoding="utf-8")

# FIX20 pacing literal belonged to the retired direct publication constructor.
p = Path("tests/test_r8_fix19.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
'    assert "inter_target_delay_seconds=5.0" in source\n',
'    container = Path("content_agent/app/container.py").read_text(encoding="utf-8")\n    assert "PublicationService(destinations)" in container\n')
p.write_text(s, encoding="utf-8")

# RC51 moved execution into CanonicalRouterBackend; test the actual invocation boundary.
p = Path("tests/test_v1_4_rc30_canonical_ai.py")
s = p.read_text(encoding="utf-8")
if "from content_agent.v2.ai.router_backend import CanonicalRouterBackend" not in s:
    s = s.replace("from content_agent import codex_runtime\n", "from content_agent import codex_runtime\nfrom content_agent.v2.ai.router_backend import CanonicalRouterBackend\n")
old = '''    def fake_invoke(slot, cfg, prompt, *, max_output_tokens, timeout_seconds, local_prompt, local_max_output_tokens):\n        captured.append(int(timeout_seconds))\n        return "AI Router працює", slot\n\n    monkeypatch.setattr(ai_router, "_invoke_route", fake_invoke)\n    result = ai_router.run_ai("test", max_output_tokens=128, cloud_timeout_seconds=10, task_timeout_seconds=90)'''
new = '''    def fake_invoke(self, slot, cfg, request, *, timeout_seconds, output_budget, local_budget):\n        del self, cfg, request, output_budget, local_budget\n        captured.append(int(timeout_seconds))\n        return "AI Router працює", slot\n\n    monkeypatch.setattr(CanonicalRouterBackend, "_invoke", fake_invoke)\n    result = ai_router.run_ai("test", max_output_tokens=128, cloud_timeout_seconds=10, task_timeout_seconds=90)'''
if old not in s:
    raise SystemExit("canonical AI stale test block not found")
s = s.replace(old, new)
p.write_text(s, encoding="utf-8")

print("RC55 stale regression contracts reconciled")
