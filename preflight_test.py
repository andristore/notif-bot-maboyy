#!/usr/bin/env python3
from pathlib import Path
import ast, re, py_compile

ROOT = Path(__file__).resolve().parent
BOT = ROOT / "bot.py"

def fail(msg):
    print("FAIL:", msg)
    raise SystemExit(1)

py_compile.compile(str(BOT), doraise=True)
tree = ast.parse(BOT.read_text(encoding="utf-8"))

defs = {}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        defs.setdefault(node.name, []).append(node.lineno)
dupes = {k:v for k,v in defs.items() if len(v) > 1}
if dupes:
    fail(f"duplicate top-level definitions: {dupes}")

text = BOT.read_text(encoding="utf-8")
env_keys = set(re.findall(r'os\.getenv\(\s*["\']([A-Z0-9_]+)["\']', text))
env_keys.discard("PORT")  # Railway injects this automatically.
env_text = (ROOT / "railway-variables.env").read_text(encoding="utf-8")
listed = set(re.findall(r'^([A-Z0-9_]+)=', env_text, flags=re.M))
missing = sorted(env_keys - listed)
if missing:
    fail(f"Railway variables missing: {missing}")

patterns = [
    (r'(?im)^DISCORD_TOKEN=.{20,}$', "DISCORD_TOKEN"),
    (r'(?im)^YOUTUBE_API_KEY=AIza[0-9A-Za-z_-]{20,}$', "YOUTUBE_API_KEY"),
    (r'(?im)^PAYMENT_WEBHOOK_SECRET=.{12,}$', "PAYMENT_WEBHOOK_SECRET"),
]
for file in ROOT.rglob("*"):
    if not file.is_file() or file.suffix in {".pyc", ".db", ".sqlite"}:
        continue
    try:
        body = file.read_text(encoding="utf-8")
    except Exception:
        continue
    for pattern, label in patterns:
        if re.search(pattern, body):
            fail(f"possible secret {label} in {file.name}")

for name in [
    "bot.py", "requirements.txt", "Procfile",
    "railway-variables.env", "RAILWAY-MIGRATION.txt", "README.md"
]:
    if not (ROOT / name).exists():
        fail(f"required file missing: {name}")

print("OK: syntax")
print("OK: no duplicate top-level definitions")
print("OK: Railway variable parity")
print("OK: basic secret scan")
print("OK: required files")
