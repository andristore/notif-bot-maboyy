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

# Class methods must not silently override each other (important for Discord UI buttons).
for node in tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    method_lines = {}
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_lines.setdefault(item.name, []).append(item.lineno)
    dup_methods = {k: v for k, v in method_lines.items() if len(v) > 1}
    if dup_methods:
        fail(f"duplicate methods in {node.name}: {dup_methods}")

# Internal base classes must be defined before subclasses.
class_lines = {
    node.name: node.lineno
    for node in tree.body
    if isinstance(node, ast.ClassDef)
}
for node in tree.body:
    if not isinstance(node, ast.ClassDef):
        continue
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in class_lines:
            if class_lines[base.id] >= node.lineno:
                fail(
                    f"class-order error: {node.name} uses {base.id} "
                    f"before it is defined"
                )

text = BOT.read_text(encoding="utf-8")
env_keys = set(re.findall(r'os\.getenv\(\s*["\']([A-Z0-9_]+)["\']', text))
for injected in {
    "PORT",
    "RAILWAY_GIT_COMMIT_SHA",
    "RAILWAY_DEPLOYMENT_ID",
}:
    env_keys.discard(injected)
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

# Runtime tuning reader must be safe before DB migrations finish.
bot_text = BOT.read_text(encoding="utf-8")
if 'if not table_exists(conn, "runtime_tuning")' not in bot_text:
    fail("runtime_tuning bootstrap guard missing")

# Regression guards for owner/payment and FREE/Premium flows.
for required_def in {
    "transaction_history_embed",
    "premium_access_effective",
    "premium_entitlements",
    "pause_excess_hosts_for_free",
    "premium_purchase_guild_ids",
    "can_purchase_premium",
    "require_premium_purchaser",
    "owner_payment_menu_embed",
    "record_premium_customer_activation",
    "premium_customer_database_rows",
    "premium_customer_database_embed",
}:
    if required_def not in defs:
        fail(f"required function missing: {required_def}")

if 'return int(premium_entitlements(int(guild_id))["host_limit"])' not in bot_text:
    fail("host limit is not routed through centralized entitlements")

for required_text in {
    'label="Premium"',
    'label="Premium DB"',
    'class PremiumCustomerDatabaseView',
    'CREATE TABLE premium_customer_ledger',
    'CREATE TABLE premium_customers',
    'INSERT OR IGNORE INTO premium_customer_ledger',
    'class PremiumGuildPickerView',
    'class PremiumGuildSelect',
    'return host_manager_has_guild_access(int(user_id), int(guild_id))',
}:
    if required_text not in bot_text:
        fail(f"Premium purchase regression guard missing: {required_text}")


# Premium production-hardening regression guards.
for required_def in {
    "commit_premium_activation",
}:
    if required_def not in defs:
        fail(f"Premium hardening function missing: {required_def}")

for required_text in {
    'activation_target_expires_at',
    'activation_effect_applied',
    'BEGIN IMMEDIATE',
    'if require_proof and scan_status != "passed"',
    'if not premium_access_effective(guild_id):',
    'Entitlement Premium diterapkan atomik.',
    '"data_export": premium',
    'interaction, self.guild_id, "data_export", "Export data server"',
}:
    if required_text not in bot_text:
        fail(f"Premium hardening regression guard missing: {required_text}")

# Active Premium invoice locking must be server-wide, not requester-wide.
create_start = bot_text.find("def create_premium_order(")
create_end = bot_text.find("\ndef get_premium_order(", create_start)
create_block = bot_text[create_start:create_end]
if "WHERE guild_id=?" not in create_block:
    fail("Premium invoice lock is not server-wide")
if "WHERE guild_id=?\n              AND requester_id=?" in create_block:
    fail("Premium invoice lock still depends on requester_id")

print("OK: syntax")
print("OK: no duplicate top-level definitions")
print("OK: class dependency order")
print("OK: Railway variable parity")
print("OK: basic secret scan")
print("OK: required files")
print("OK: bootstrap guards")
print("OK: owner/payment regression guards")
print("OK: FREE/Premium entitlement guards")
print("OK: Premium purchase access + UI guards")
print("OK: no duplicate class methods")
print("OK: Premium customer database guards")
print("OK: Premium production hardening guards")
