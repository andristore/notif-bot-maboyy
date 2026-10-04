#!/usr/bin/env python3
"""
Runtime smoke-test.
Install requirements first:
    pip install -r requirements.txt
Then run:
    python smoke_test.py

If discord.py is unavailable, this script exits as SKIP instead of reporting a
false failure.
"""
import os, tempfile, importlib.util
from pathlib import Path

try:
    import discord  # noqa: F401
except ModuleNotFoundError:
    print("SKIP: discord.py belum terpasang. Jalankan pip install -r requirements.txt")
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parent

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DB_PATH"] = str(Path(tmp) / "smoke.db")
    os.environ["AUTO_BACKUP_DIR"] = str(Path(tmp) / "backups")
    os.environ["QRIS_STORAGE_DIR"] = str(Path(tmp) / "qris")
    os.environ["DISCORD_TOKEN"] = ""
    os.environ["OWNER_IDS"] = "1"
    os.environ["PAYMENT_WEBHOOK_ENABLED"] = "false"

    spec = importlib.util.spec_from_file_location("hinotif_smoke", ROOT / "bot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.validate_storage_paths_before_db()
    mod.migrate_database()

    with mod.closing(mod.db()) as conn:
        tables = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    required = {
        "premium_orders", "hosts", "guild_settings",
        "pending_notifications", "payment_callback_events",
        "user_verifications", "guild_owner_verification"
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"migration missing tables: {missing}")

    order_id = mod.create_premium_order(999001, 888001, 30, 25000)
    order = mod.get_premium_order(order_id)
    expected = int(order["expected_amount"])
    assert expected > 25000
    assert mod.verify_received_amount(order_id, expected) is True

    ok, detail = mod.backup_restore_smoke_test({
        "version": 5,
        "created_at": 0,
        "guilds": [{
            "guild_id": 999001,
            "hosts": [{"platform": "youtube", "target": "test"}]
        }]
    })
    assert ok, detail

    print("OK: migration")
    print("OK: invoice + unique code")
    print("OK: amount verification")
    print("OK: backup restore smoke-test")
