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
    'snapshot = user_access_snapshot(int(user_id), int(guild_id))',
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

# Premium Stability Pack v1.13 regression guards.
for required_def in {
    "premium_status_snapshot",
    "premium_downgrade_preview",
    "premium_usage_metrics",
    "premium_usage_embed",
    "premium_health_report",
    "repair_premium_customer_ledger",
    "persist_payment_proof_file",
    "register_payment_proof_attempt",
    "premium_invoice_abuse_check",
    "reconcile_premium_after_refund",
}:
    if required_def not in defs:
        fail(f"Premium Stability Pack function missing: {required_def}")

for required_text in {
    'CREATE TABLE IF NOT EXISTS premium_feature_usage',
    'CREATE TABLE IF NOT EXISTS premium_health_audit',
    'proof_storage_path',
    'proof_upload_attempts',
    'premium_recovery_watchdog_loop',
    'premium_health_watch_loop',
    'label="Health"',
    'label="Analytics"',
    'proof_upload_limit',
    'source="recovery_watchdog"',
    'reconcile_premium_after_refund',
    'dm_latest_premium_buyer',
}:
    if required_text not in bot_text:
        fail(f"Premium Stability Pack guard missing: {required_text}")

# Premium payment UX + anti-spam backup guards (v1.14).
for required_def in {
    "claim_auto_backup_run",
    "complete_auto_backup_run",
    "release_auto_backup_run",
    "should_notify_auto_backup_owner",
    "latest_open_premium_order",
    "open_user_premium_payment",
}:
    if required_def not in defs:
        fail(f"v1.14 function missing: {required_def}")

for required_text in {
    'CREATE TABLE IF NOT EXISTS auto_backup_state',
    'BEGIN IMMEDIATE',
    'label="Pembayaran"',
    'label="Buat Invoice & Bayar"',
    'recover_payment_methods_if_empty',
    'Invoice **belum dibuat**',
    'preferred_qris',
    'Auto backup owner DM dilewati untuk mencegah spam.',
}:
    if required_text not in bot_text:
        fail(f"v1.14 regression guard missing: {required_text}")

print("OK: Premium payment UX + auto-backup anti-spam v1.14 guards")


# Premium quote/unique-code preview guards (v1.14.2).
for required_def in {
    "get_or_create_premium_payment_quote",
    "get_premium_payment_quote",
}:
    if required_def not in defs:
        fail(f"v1.14.2 quote function missing: {required_def}")

for required_text in {
    'CREATE TABLE IF NOT EXISTS premium_payment_quotes',
    'PREMIUM_QUOTE_TTL_SECONDS',
    'Kode unik:',
    'Total transfer:',
    'quote_id=self.quote_id',
    'consumed_at',
}:
    if required_text not in bot_text:
        fail(f"v1.14.2 quote regression guard missing: {required_text}")

print("OK: Premium quote + unique-code preview v1.14.2 guards")


# Premium audit hardening v1.14.4.
for required_def in {
    "payment_method_usable",
    "list_usable_payment_methods",
    "rollback_unpaid_premium_order",
}:
    if required_def not in defs:
        fail(f"v1.14.4 Premium audit function missing: {required_def}")

for required_text in {
    "list_usable_payment_methods()",
    "late_payment", "refund_pending",
    "rollback_unpaid_premium_order(order_id, self.quote_id)",
    "next_status = current_status",
    'not settings["premium_expires_at"] or effective_until > int(time.time())',
}:
    if required_text not in bot_text:
        fail(f"v1.14.4 Premium audit guard missing: {required_text}")

print("OK: Premium audit hardening v1.14.4 guards")

strict_needles = [
    'proof_manual_approved',
    'proof_reviewed_by',
    'proof_perceptual_hash',
    'approve_payment_proof_manually',
    'label="Lihat Bukti"',
    'label="Bukti Valid & Aktif"',
    'Screening otomatis hanya memeriksa kualitas/indikator teknis',
    'distance <= 4',
]
for needle in strict_needles:
    if needle not in bot_text:
        fail(f"Premium strict payment guard missing: {needle}")
print("OK: Premium strict payment review v1.15 guards")

# Ensure every explicitly declared Discord component custom_id is unique.
custom_ids = re.findall(r'custom_id\s*=\s*["\']([^"\']+)["\']', bot_text)
seen = set()
duplicate_custom_ids = set()
for cid in custom_ids:
    if cid in seen:
        duplicate_custom_ids.add(cid)
    seen.add(cid)
if duplicate_custom_ids:
    fail(f"duplicate explicit custom_id values: {sorted(duplicate_custom_ids)}")

print("OK: Premium Stability Pack v1.13 guards")
print("OK: explicit custom_id uniqueness")

# Role & Permission Separation v1.16 guards.
for required_def in {
    "user_access_snapshot",
    "require_user_panel",
    "require_host_manager_scope",
}:
    if required_def not in defs:
        fail(f"v1.16 access separation function missing: {required_def}")

for required_text in {
    '"premium_purchaser": bool(server_owner or host_manager)',
    'snapshot = user_access_snapshot(int(user_id), int(guild_id))',
    'Akses dipisahkan:',
    'async def interaction_check(self, interaction: discord.Interaction) -> bool:',
    'Akses Host Manager-mu sudah tidak aktif.',
    'pembelian Premium tidak mengubah role atau izin',
}:
    if required_text not in bot_text:
        fail(f"v1.16 access separation guard missing: {required_text}")

print("OK: Role & Permission Separation v1.16 guards")


# Owner Update Info Center v1.17 guards.
for required_def in {
    "get_bot_update_settings",
    "set_bot_update_channel",
    "bot_update_target_channel",
    "bot_update_embed",
    "send_bot_update_announcement",
    "announce_current_version_if_needed",
    "owner_update_center_embed",
}:
    if required_def not in defs:
        fail(f"v1.17 update center function missing: {required_def}")

for required_text in {
    'CREATE TABLE IF NOT EXISTS bot_update_settings',
    'CREATE TABLE IF NOT EXISTS bot_update_history',
    'class OwnerUpdateCenterView',
    'class OwnerUpdateChannelModal',
    'class OwnerUpdateAnnouncementModal',
    'label="Update Info"',
    'label="Set Channel"',
    'label="Kirim Update"',
    'label="Test Channel"',
    'label="Auto Versi"',
    'await announce_current_version_if_needed()',
    'last_announced_version',
    'pending_version',
    'REQUIRED_GUILD_ID',
    'Informasi Update Resmi',
}:
    if required_text not in bot_text:
        fail(f"v1.17 update center guard missing: {required_text}")

if 'APP_VERSION = "1.18.0"' not in bot_text:
    fail("v1.18 APP_VERSION missing")
if 'CURRENT_SCHEMA_VERSION = 31' not in bot_text:
    fail("v1.18 schema version missing")

print("OK: Owner Update Info Center v1.17 guards")

# Operations & Support hardening v1.18 guards.
for required_def in {
    "feature_maintenance_enabled",
    "set_feature_maintenance",
    "support_channel_id",
    "set_support_channel",
    "support_ticket_rows",
    "recent_interaction_errors",
    "owner_support_embed",
    "owner_feature_maintenance_embed",
    "owner_system_health_embed",
}:
    if required_def not in defs:
        fail(f"v1.18 operations/support function missing: {required_def}")

for required_text in {
    'CREATE TABLE IF NOT EXISTS feature_maintenance',
    'CREATE TABLE IF NOT EXISTS support_tickets',
    'CREATE TABLE IF NOT EXISTS support_settings',
    'CREATE TABLE IF NOT EXISTS interaction_errors',
    'class UserSupportModal',
    'class OwnerSupportCenterView',
    'class OwnerFeatureMaintenanceView',
    'class OwnerSystemHealthView',
    'class OwnerErrorLookupModal',
    'label="Bantuan"',
    'label="Maintenance"',
    'label="Health"',
    'label="Cari Error ID"',
    'feature_maintenance_enabled("notifications")',
    'def latest_activated_premium_package',
    'label="Perpanjang Sama"',
}:
    if required_text not in bot_text:
        fail(f"v1.18 operations/support guard missing: {required_text}")

print("OK: Operations, support, error-id and feature-maintenance v1.18 guards")
