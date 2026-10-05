"""Offline regression tests using production functions and temporary SQLite.

Discord/network boundaries are faked; these tests never import/start the bot,
read deployment secrets, or use a production database.
"""
import ast
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import zipfile
from zoneinfo import ZoneInfo
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
SOURCE = ast.parse((ROOT / "bot.py").read_text(encoding="utf-8"))
FUNCTIONS = {
    "canonical_tiktok_username", "canonical_tiktok_url", "valid_public_http_url",
    "host_public_url", "notification_link_view", "tiktok_live_card_title",
    "build_tiktok_live_embed", "suppress_redundant_live_content",
    "payment_checkout_state", "payment_checkout_embed", "payment_receipt_eligible",
    "payment_receipt_image_bytes", "payment_receipt_embed", "send_payment_receipt",
    "latest_user_premium_order",
    "get_payment_method", "payment_method_usable", "assign_order_payment_method", "save_payment_proof_details",
    "is_user_in_required_guild", "refresh_user_verification", "refresh_guild_owner_verification",
    "verify_owned_guilds_for_user", "verify_support_button", "require_support_membership",
    "start_verify_embed", "menu_command", "invoice_deadline_text", "required_guild_invite_url",
    "require_user_panel", "require_server_owner", "require_premium_purchaser", "on_guild_join",
    "invoice_display_details", "invoice_image_bytes", "invoice_status_label",
    "db", "table_exists", "columns", "add_column_if_missing", "migrate_database",
    "ensure_guild", "get_config", "get_guild_settings", "get_hosts", "get_host", "rupiah",
    "get_runtime_tuning", "runtime_tuning_int", "normalize_social_target",
    "restore_guild_backup", "export_guild_backup", "backup_payload_checksum",
    "create_full_backup_payload", "manual_backup_payload_and_bytes",
    "create_full_system_backup_zip", "prune_system_backups", "prune_auto_backups",
    "get_order_by_invoice_ref", "get_premium_order", "payment_transition_allowed",
    "payment_reference_in_use", "process_verified_payment_event",
    "claim_order_for_activation", "commit_premium_activation", "release_order_claim",
    "activate_verified_premium_order", "verify_payment_webhook_signature",
    "record_payment_callback_event", "mark_callback_event", "enqueue_payment_event_dlq",
    "payment_webhook_handler", "record_delivery_attempt", "record_notification_history",
    "reserve_notification_event", "release_notification_event", "queue_notification_retry",
    "notifications_paused", "send_notification", "_deliver_notification_now",
    "pending_notification_loop", "move_notification_to_dead_letter", "event_cleanup_loop",
    "get_live_state", "update_live_state", "live_transition_confirmed", "check_tiktok_live",
}


class Embed:
    title = "Test notification"

    def to_dict(self):
        return {"title": self.title}

    @classmethod
    def from_dict(cls, data):
        return cls()


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.app = {
            "os": os, "Path": Path, "sqlite3": sqlite3, "closing": closing,
            "time": time, "datetime": datetime, "timezone": timezone,
            "ZoneInfo": ZoneInfo, "json": json, "hashlib": hashlib, "hmac": hmac,
            "quote": quote, "unquote": unquote, "urlparse": urlparse, "APP_VERSION": "1.25.7",
            "re": re, "asyncio": asyncio, "io": io, "tempfile": tempfile,
            "zipfile": zipfile, "__file__": str(ROOT / "bot.py"),
            "log": logging.getLogger("reliability-tests"),
            "DB_PATH": str(folder / "test.db"), "QRIS_STORAGE_DIR": str(folder / "qris"),
            "AUTO_BACKUP_DIR": str(folder / "backups"), "AUTO_BACKUP_KEEP": 2,
            "DEFAULT_CHECK_INTERVAL": 120, "MONITOR_CONCURRENCY": 5,
            "PREMIUM_PACKAGES": [(30, 25000)], "NOTIFICATION_MAX_RETRIES": 3,
            "ERROR_ALERT_THRESHOLD": 5, "REQUIRED_GUILD_ID": 0,
            "FREE_HOST_LIMIT": 3, "CURRENT_SCHEMA_VERSION": 36,
            "NOTIFICATION_RETRY_SECONDS": 60, "NOTIFICATION_CLAIM_TIMEOUT_SECONDS": 300,
            "RUNTIME_SESSION_ID": "test-session", "SMART_LIVE_CONFIRMATIONS": 1,
            "NOTIFICATION_MIN_DELAY_MS": 0, "EVENT_RETENTION_DAYS": 30,
            "AUTO_ACTIVATE_VERIFIED_PAYMENTS": True,
            "PAYMENT_WEBHOOK_SECRET": "offline-test-secret",
            "PAYMENT_WEBHOOK_MAX_SKEW_SECONDS": 300, "PAYMENT_EVENT_RETRY_SECONDS": 120,
            "runtime_metrics": {k: 0 for k in ("notifications_sent", "notifications_failed", "notifications_queued")},
            "notification_send_semaphore": asyncio.Semaphore(1),
            "bot": SimpleNamespace(guilds=[SimpleNamespace(id=1)], get_guild=lambda _: SimpleNamespace(id=1, owner_id=9, name="Test Server")),
            "http": None,
        }
        for node in SOURCE.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in {"SUPPORTED_PLATFORMS", "PAYMENT_STATE_TRANSITIONS"}:
                    # The payment map includes empty set() calls, so execute the assignment.
                    exec(compile(ast.Module(body=[node], type_ignores=[]), "constants", "exec"), self.app)
        import copy
        nodes = []
        for node in SOURCE.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
                node = copy.deepcopy(node)
                node.decorator_list = []
                nodes.append(node)
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(ROOT / "bot.py"), "exec"), self.app)
        self.production = {name: self.app[name] for name in FUNCTIONS}
        self.app["migrate_database"]()
        self.app["ensure_guild"](1)
        self.app.update({
            "refresh_payment_risk": Mock(), "record_premium_event": Mock(),
            "reactivate_plan_paused_hosts": Mock(return_value=0), "add_activity": Mock(),
            "record_premium_customer_activation": Mock(), "premium_expiry_text": Mock(return_value="future"),
            "audit_webhook": AsyncMock(), "send_payment_admin_log": AsyncMock(),
            "notify_order_user": AsyncMock(), "send_payment_receipt": AsyncMock(),
            "payment_health_update": Mock(), "apply_host_embed_branding": Mock(),
            "suppress_redundant_live_content": lambda h, c, e: c,
            "host_mention_roles": Mock(return_value=[]), "host_delivery_channels": Mock(return_value=[10, 20]),
            "notification_link_view": Mock(return_value=None), "premium_feature_enabled": Mock(return_value=True),
            "host_quiet_now": Mock(return_value=False), "runtime_setting_enabled": Mock(return_value=False),
            "feature_maintenance_enabled": Mock(return_value=False),
            "guild_owner_verified": AsyncMock(return_value=True),
            "is_global_owner": Mock(return_value=False),
            "set_user_verification": Mock(), "set_guild_owner_verification": Mock(),
            "maybe_activate_premium_trial": Mock(return_value=None),
            "safe_reply": AsyncMock(), "defer_if_needed": AsyncMock(), "dm_guild_owner": AsyncMock(),
            "discord": SimpleNamespace(Embed=Embed, AllowedMentions=lambda **kw: kw),
        })
        self.execute("INSERT INTO hosts(guild_id,platform,target,enabled,check_interval) VALUES(1,'tiktok','creator',1,120)")
        self.host = self.app["get_host"](1)

    def card_boundary(self):
        class Card:
            def __init__(self, **kw): self.__dict__.update(kw); self.fields = []
            def set_author(self, **kw): self.author = kw
            def set_image(self, **kw): self.image = kw
            def add_field(self, **kw): self.fields.append(kw)
            def set_footer(self, **kw): self.footer = kw
        class View:
            def __init__(self, **kw): self.children = []
            def add_item(self, item): self.children.append(item)
        self.app["discord"] = SimpleNamespace(
            Embed=Card, Color=SimpleNamespace(from_rgb=lambda *args: args),
            ui=SimpleNamespace(View=View, Button=lambda **kw: SimpleNamespace(**kw)),
            ButtonStyle=SimpleNamespace(link=5))

    def test_tiktok_username_url_variants(self):
        for value in ("@Maboyynt", "www.tiktok.com/@Maboyynt/live?x=1",
                      "https://m.tiktok.com/@Maboyynt", "https://www.tiktok.com/%40Maboyynt"):
            with self.subTest(value=value):
                self.assertEqual(self.app["normalize_social_target"]("tiktok", value), "Maboyynt")
                self.assertEqual(self.app["canonical_tiktok_url"](value), "https://www.tiktok.com/@Maboyynt")
        for value in ("https://evil.example/@Maboyynt", "https://vm.tiktok.com/share", "bad name"):
            self.assertEqual(self.app["canonical_tiktok_username"](value), "")

    def test_live_profile_buttons_enabled_and_canonical(self):
        self.card_boundary()
        host = {"platform": "tiktok", "target": "m.tiktok.com/@Maboyynt/live"}
        view = self.production["notification_link_view"](host, "https://redirect.example/track", "tiktok_live_test")
        self.assertEqual([b.url for b in view.children], ["https://www.tiktok.com/@Maboyynt/live", "https://www.tiktok.com/@Maboyynt"])
        self.assertEqual(view.children[1].label, "Profil TikTok")
        self.assertTrue(all(b.style == 5 and b.disabled is False for b in view.children))
        self.assertTrue(all(not hasattr(b, "custom_id") for b in view.children))

    def test_profile_button_without_source_and_invalid_target(self):
        self.card_boundary()
        host = {"platform": "tiktok", "target": "@Maboyynt"}
        view = self.production["notification_link_view"](host, None)
        self.assertEqual(len(view.children), 1)
        self.assertEqual(view.children[0].label, "Profil TikTok")
        self.assertIsNone(self.production["notification_link_view"]({"platform": "tiktok", "target": "bad name"}, None))

    def test_stock_title_and_author_do_not_repeat_username(self):
        self.card_boundary()
        host = {"display_name": "Maboyynt"}
        for title in ("@Maboyynt LIVE", "Maboyynt is live!", "", "@Maboyynt sedang LIVE!"):
            card = self.app["build_tiktok_live_embed"](host, "Maboyynt", {"title": title}, test=True)
            self.assertEqual(card.title, "TikTok LIVE • TEST")
            self.assertEqual(card.author["name"], "@Maboyynt")

    def test_actual_title_thumbnail_and_display_name_preserved(self):
        self.card_boundary()
        card = self.app["build_tiktok_live_embed"]({"display_name": "Maboyynt"}, "Maboyynt", {
            "title": "semangat awal bulan sahabat", "uploader": "Atapu", "thumbnail": "https://example.com/photo.jpg"})
        self.assertEqual(card.title, "semangat awal bulan sahabat")
        self.assertEqual(card.author["name"], "Atapu")
        self.assertEqual(card.image["url"], "https://example.com/photo.jpg")

    def invoice_order(self, **changes):
        order = dict(id=42, invoice_ref="CONTOH-INV-20261005-000042", guild_id=123456789012345678,
                     requester_id=987654321098765432, days=30, price=25000, unique_code=123,
                     expected_amount=25123, received_amount=None, payment_method_name="QRIS",
                     created_at=1791216000, invoice_deadline=1791219600, status="pending",
                     expires_at=None, activated_at=None, paid_at=None, payment_verified_at=None,
                     amount_verified=0, payment_method_id=1, receipt_sent_at=None)
        order.update(changes)
        return order

    def test_invoice_details_preserve_billing_values_and_wib(self):
        order = self.invoice_order()
        snapshot = dict(order)
        details = self.app["invoice_display_details"](order)
        self.assertEqual(details["total"], 25123)
        self.assertEqual(details["unique_code"], 123)
        self.assertEqual(details["created"], "05/10/2026 23:00 WIB")
        self.assertEqual(details["deadline"], "06/10/2026 00:00 WIB")
        self.assertEqual(details["status_label"], "Menunggu Pembayaran")
        self.assertEqual(order, snapshot)

    def test_invoice_details_missing_values_and_paid_status(self):
        fn = self.app["invoice_display_details"]
        details = fn(self.invoice_order(expected_amount=None, unique_code=None, invoice_deadline=None, payment_method_name=None))
        self.assertEqual(details["total"], 25000)
        self.assertEqual(details["method"], "Belum dipilih")
        self.assertEqual(details["deadline"], "Belum ditentukan")
        self.assertEqual(fn(self.invoice_order(expected_amount=0))["total"], 0)
        details = fn(self.invoice_order(status="active", received_amount=25123))
        self.assertEqual(details["status_label"], "Aktif")
        self.assertEqual(details["received"], 25123)

    def test_invoice_png_status_variants_and_font_fallback(self):
        from PIL import Image, ImageDraw, ImageFont
        self.app.update(Image=Image, ImageDraw=ImageDraw, ImageFont=ImageFont)
        for status in ("pending", "active", "invoice_expired", "refund_pending"):
            with self.subTest(status=status):
                content = self.app["invoice_image_bytes"](self.invoice_order(status=status))
                with Image.open(io.BytesIO(content)) as im:
                    self.assertEqual(im.size, (1200, 1560))
                    self.assertEqual(im.format, "PNG")
                    self.assertNotEqual(im.getpixel((0, 0)), (255, 255, 255))
                with Image.open(io.BytesIO(content)) as im:
                    im.verify()
        original = ImageFont.truetype
        def missing_external(font, *args, **kwargs):
            if isinstance(font, str):
                raise OSError("no system fonts")
            return original(font, *args, **kwargs)
        with unittest.mock.patch.object(ImageFont, "truetype", side_effect=missing_external):
            content = self.app["invoice_image_bytes"](self.invoice_order(invoice_ref="R"*160, payment_method_name="Metode "*40))
            self.assertTrue(content.startswith(b"\x89PNG"))


    def load_payment_views(self):
        import discord
        self.app["discord"] = discord
        wanted = {"PaymentConfirmView", "StartVerifyView", "GuildJoinVerifyView"}
        import copy
        nodes = [copy.deepcopy(n) for n in SOURCE.body if isinstance(n, ast.ClassDef) and n.name in wanted]
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "production-views", "exec"), self.app)
        self.app["REQUIRED_GUILD_INVITE"] = "https://discord.gg/example"

    def test_checkout_states_separate_payment_from_activation(self):
        fn = self.app["payment_checkout_state"]
        pending = fn(self.invoice_order(invoice_deadline=int(time.time())+600))
        self.assertTrue(pending["can_pay"])
        paid = fn(self.invoice_order(status="paid", amount_verified=1, paid_at=123))
        self.assertFalse(paid["can_pay"])
        self.assertEqual(paid["step"], 2)
        self.assertIn("menunggu aktivasi", paid["instruction"])
        active = fn(self.invoice_order(status="active", activated_at=123))
        self.assertEqual(active["step"], 3)
        self.assertTrue(active["can_receipt"])
        expired = fn(self.invoice_order(invoice_deadline=1))
        self.assertEqual(expired["status"], "invoice_expired")
        self.assertFalse(expired["can_pay"])

    async def test_checkout_embed_and_button_states(self):
        self.load_payment_views()
        order = self.invoice_order(invoice_deadline=int(time.time())+600)
        self.app["get_premium_order"] = Mock(return_value=order)
        view = self.app["PaymentConfirmView"](42)
        buttons = {child.label: child for child in view.children}
        self.assertEqual(len(buttons), 8)
        self.assertFalse(buttons["Cek Status"].disabled)
        self.assertTrue(buttons["Kuitansi"].disabled)
        self.assertFalse(buttons["Metode / Bayar"].disabled)
        order.update(status="active", activated_at=123)
        view = self.app["PaymentConfirmView"](42)
        buttons = {child.label: child for child in view.children}
        self.assertFalse(buttons["Kuitansi"].disabled)
        self.assertTrue(buttons["Saya Sudah Bayar"].disabled)
        self.assertTrue(buttons["Metode / Bayar"].disabled)
        self.assertTrue(all(len(row["components"]) <= 5 for row in view.to_components()))
        embed = self.app["payment_checkout_embed"](order)
        self.assertIn("Rp25.123", str(embed.to_dict()))
        self.assertNotIn("Risk", str(embed.to_dict()))

    async def test_payment_panel_rejects_other_requester(self):
        self.load_payment_views()
        self.app["get_premium_order"] = Mock(return_value=self.invoice_order())
        interaction = SimpleNamespace(user=SimpleNamespace(id=99))
        self.assertFalse(await self.app["PaymentConfirmView"](42).interaction_check(interaction))
        self.app["safe_reply"].assert_awaited_once()

    def test_receipt_requires_recorded_confirmation(self):
        fn = self.app["payment_receipt_eligible"]
        for status in ("pending", "proof_submitted", "rejected", "invoice_expired", "refunded"):
            self.assertFalse(fn(self.invoice_order(status=status)))
        self.assertFalse(fn(self.invoice_order(status="paid")))
        self.assertFalse(fn(self.invoice_order(status="amount_verified", amount_verified=1)))
        self.assertTrue(fn(self.invoice_order(status="paid", amount_verified=1, paid_at=123)))
        self.assertTrue(fn(self.invoice_order(status="active", activated_at=123)))
        with self.assertRaises(ValueError):
            self.app["payment_receipt_image_bytes"](self.invoice_order())

    async def test_receipt_png_and_embed_use_real_confirmation_timestamp(self):
        self.load_payment_views()
        from PIL import Image, ImageDraw, ImageFont
        self.app.update(Image=Image, ImageDraw=ImageDraw, ImageFont=ImageFont)
        order = self.invoice_order(status="active", activated_at=1791216000, paid_at=1791215900, received_amount=25123, expires_at=1793808000)
        embed = self.app["payment_receipt_embed"](order)
        self.assertIn("<t:1791215900:F>", str(embed.to_dict()))
        png = self.app["payment_receipt_image_bytes"](order)
        with Image.open(io.BytesIO(png)) as im:
            self.assertEqual(im.size, (1200,1560)); im.verify()

    async def test_receipt_sender_blocks_unpaid_order(self):
        self.app["get_premium_order"] = Mock(return_value=self.invoice_order())
        self.assertFalse(await self.production["send_payment_receipt"](42))

    async def test_confirmed_receipt_sent_once_with_png_attachment(self):
        self.load_payment_views()
        from PIL import Image, ImageDraw, ImageFont
        self.app.update(Image=Image, ImageDraw=ImageDraw, ImageFont=ImageFont)
        self.new_order("active",activated=True)
        user = SimpleNamespace(send=AsyncMock())
        self.app["bot"].get_user = Mock(return_value=user)
        fn = self.production["send_payment_receipt"]
        self.assertTrue(await fn(1))
        self.assertIn("file",user.send.call_args.kwargs)
        self.assertTrue(await fn(1))
        user.send.assert_awaited_once()
        self.assertTrue(self.execute("SELECT receipt_sent_at FROM premium_orders WHERE id=1")[0][0])

    def test_method_change_rejects_settled_and_overdue_orders(self):
        self.new_order()
        order = self.app["get_order_by_invoice_ref"]("TEST-INVOICE")
        self.app["get_payment_method"] = Mock(return_value={"method_name": "QRIS"})
        self.app["payment_method_usable"] = Mock(return_value=True)
        self.app["assign_order_payment_method"](order["id"], 1)
        self.execute("UPDATE premium_orders SET status='active' WHERE id=?", (order["id"],))
        with self.assertRaises(ValueError): self.app["assign_order_payment_method"](order["id"], 2)
        self.execute("UPDATE premium_orders SET status='pending', invoice_deadline=1 WHERE id=?", (order["id"],))
        with self.assertRaises(ValueError): self.app["assign_order_payment_method"](order["id"], 2)
        self.assertEqual(self.execute("SELECT payment_method_id FROM premium_orders WHERE id=?",(order["id"],))[0][0],1)

    def test_latest_transaction_is_scoped_to_requester_and_server(self):
        self.new_order()
        self.assertIsNotNone(self.app["latest_user_premium_order"](1,1))
        self.assertIsNone(self.app["latest_user_premium_order"](2,1))
        self.assertIsNone(self.app["latest_user_premium_order"](1,2))

    def test_proof_details_cannot_change_settled_or_expired_invoice(self):
        self.new_order()
        values = dict(sender_name="Test",sender_account="123",transfer_time="WIB",reference="PROOF-1",declared_amount=25123)
        self.app["save_payment_proof_details"](1,**values)
        self.execute("UPDATE premium_orders SET status='active'")
        values["reference"] = "PROOF-2"
        with self.assertRaises(ValueError): self.app["save_payment_proof_details"](1,**values)
        self.execute("UPDATE premium_orders SET status='pending',invoice_deadline=1")
        with self.assertRaises(ValueError): self.app["save_payment_proof_details"](1,**values)
        self.assertEqual(self.execute("SELECT proof_reference FROM premium_orders")[0][0],"PROOF-1")

    def test_support_invite_accepts_only_discord_https_links(self):
        for url in ("https://discord.gg/abc", "https://discord.com/invite/abc"):
            self.app["REQUIRED_GUILD_INVITE"] = url
            self.assertEqual(self.app["required_guild_invite_url"](),url)
        for url in ("http://discord.gg/abc", "https://evil.example/invite/abc", "https://discord.com/channels/abc", "https://discord.gg/"):
            self.app["REQUIRED_GUILD_INVITE"] = url
            self.assertEqual(self.app["required_guild_invite_url"](),"")

    async def test_failed_verify_button_never_unlocks_owned_guilds(self):
        self.load_payment_views()
        self.app["REQUIRED_GUILD_ID"] = 10
        self.app["is_user_in_required_guild"] = AsyncMock(return_value=False)
        self.app["verify_owned_guilds_for_user"] = AsyncMock()
        interaction = SimpleNamespace(user=SimpleNamespace(id=9))
        self.assertFalse(await self.app["verify_support_button"](interaction))
        self.app["verify_owned_guilds_for_user"].assert_not_awaited()
        self.assertFalse(self.app["set_user_verification"].call_args.args[1])

    async def test_membership_ignores_stale_member_cache(self):
        self.load_payment_views()
        discord = self.app["discord"]
        self.app["REQUIRED_GUILD_ID"] = 10
        guild = SimpleNamespace(get_member=Mock(return_value=object()), fetch_member=AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "missing")))
        self.app["bot"].get_guild = Mock(return_value=guild)
        self.assertFalse(await self.app["is_user_in_required_guild"](9))
        guild.fetch_member.assert_awaited_once_with(9)
        guild.get_member.assert_not_called()
        guild.fetch_member = AsyncMock(return_value=object())
        self.assertTrue(await self.app["is_user_in_required_guild"](9))

    async def test_membership_missing_config_and_forbidden_fail_closed(self):
        self.load_payment_views()
        self.assertFalse(await self.app["is_user_in_required_guild"](9))
        self.app["REQUIRED_GUILD_ID"] = 10
        self.app["bot"].get_guild = Mock(return_value=None)
        self.assertFalse(await self.app["is_user_in_required_guild"](9))
        discord = self.app["discord"]
        guild = SimpleNamespace(fetch_member=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "denied")))
        self.app["bot"].get_guild = Mock(return_value=guild)
        self.assertFalse(await self.app["is_user_in_required_guild"](9))

    async def test_server_verification_missing_config_does_not_unlock(self):
        guild = SimpleNamespace(id=1, owner_id=9)
        self.assertFalse(await self.app["refresh_guild_owner_verification"](guild))
        self.assertFalse(self.app["set_guild_owner_verification"].call_args.args[2])

    async def test_join_button_persists_user_and_owned_guild_verification(self):
        self.load_payment_views()
        self.app["REQUIRED_GUILD_ID"] = 10
        self.app["is_user_in_required_guild"] = AsyncMock(return_value=True)
        self.app["refresh_guild_owner_verification"] = AsyncMock(return_value=True)
        self.app["bot"].guilds = [SimpleNamespace(id=1, owner_id=9), SimpleNamespace(id=2, owner_id=22)]
        interaction = SimpleNamespace(user=SimpleNamespace(id=9))
        self.assertTrue(await self.app["verify_support_button"](interaction))
        self.app["set_user_verification"].assert_called_once()
        self.app["refresh_guild_owner_verification"].assert_awaited_once()
        self.app["maybe_activate_premium_trial"].assert_called_once_with(1,9,source="verified_support_join")

    async def test_public_onboarding_rejects_non_owner_and_is_persistent(self):
        self.load_payment_views()
        view = self.app["GuildJoinVerifyView"]()
        self.assertTrue(view.is_persistent())
        self.app["verify_support_button"] = AsyncMock()
        button = next(b for b in view.children if b.label == "Verifikasi Join")
        interaction = SimpleNamespace(user=SimpleNamespace(id=99), guild=SimpleNamespace(owner_id=9))
        await button.callback(interaction)
        self.app["verify_support_button"].assert_not_awaited()
        interaction.user.id = 9
        await button.callback(interaction)
        self.app["verify_support_button"].assert_awaited_once_with(interaction)

    async def test_retained_user_record_does_not_bypass_menu_live_check(self):
        self.load_payment_views()
        self.app.update(SAFE_MODE=False, REQUIRED_GUILD_ID=10, require_dm_command=AsyncMock(return_value=True),
                        is_user_blacklisted=Mock(return_value=False), action_rate_limited=Mock(return_value=False),
                        user_verification_is_active=Mock(return_value=True), refresh_user_verification=AsyncMock(return_value=False))
        interaction = SimpleNamespace(user=SimpleNamespace(id=9))
        await self.app["menu_command"](interaction)
        self.app["refresh_user_verification"].assert_awaited_once()
        self.app["user_verification_is_active"].assert_not_called()
        self.assertIsInstance(self.app["safe_reply"].call_args.kwargs["view"], self.app["StartVerifyView"])

    async def test_unverified_pending_delivery_holds_without_retry(self):
        self.app["notifications_paused"] = Mock(return_value=True)
        await self.app["send_notification"](self.host, Embed(), None, event_type="test", source_url="https://example.com")
        self.execute("UPDATE pending_notifications SET release_after=0")
        self.app["notifications_paused"] = Mock(return_value=False)
        self.app["guild_owner_verified"] = AsyncMock(return_value=False)
        self.app["claim_pending_notification"] = Mock()
        await self.app["pending_notification_loop"]()
        self.app["claim_pending_notification"].assert_not_called()
        self.assertEqual(self.execute("SELECT retry_count FROM pending_notifications")[0][0],0)

    async def test_direct_delivery_cannot_bypass_membership_gate(self):
        self.app["guild_owner_verified"] = AsyncMock(return_value=False)
        self.app["resolve_channel"] = AsyncMock()
        result = await self.app["_deliver_notification_now"](self.host, Embed(), None, event_type="test", event_key="gate", source_url=None)
        self.assertFalse(result)
        self.app["resolve_channel"].assert_not_awaited()

    async def test_guild_install_sends_join_buttons_without_starting_trial(self):
        self.load_payment_views()
        self.app["refresh_guild_owner_verification"] = AsyncMock(return_value=False)
        self.app["primary_owner_ids"] = Mock(return_value=[])
        self.app["required_join_text"] = Mock(return_value="Join support")
        owner = SimpleNamespace(send=AsyncMock())
        channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("no permission")), permissions_for=lambda _: SimpleNamespace(view_channel=True,send_messages=True,embed_links=True))
        guild = SimpleNamespace(id=1, name="Test", owner_id=9, owner=owner, system_channel=channel, me=object(),text_channels=[])
        await self.app["on_guild_join"](guild)
        self.app["maybe_activate_premium_trial"].assert_not_called()
        self.assertIsInstance(channel.send.call_args.kwargs["view"],self.app["GuildJoinVerifyView"])
        self.assertIsInstance(owner.send.call_args.kwargs["view"],self.app["StartVerifyView"])

    def test_live_card_has_profile_link_without_metadata(self):
        self.card_boundary()
        card = self.app["build_tiktok_live_embed"]({"display_name": "Maboyynt"}, "Maboyynt")
        links = next(f["value"] for f in card.fields if f["name"] == "Tautan")
        self.assertIn("[👤 Profil TikTok](https://www.tiktok.com/@Maboyynt)", links)
        self.assertIn("[▶️ Tonton LIVE](https://www.tiktok.com/@Maboyynt/live)", links)
        self.assertEqual(card.author["url"], "https://www.tiktok.com/@Maboyynt")

    async def test_real_discord_link_payload(self):
        import discord
        self.app["discord"] = discord
        host = {"platform": "tiktok", "target": "@Maboyynt", "display_name": "Maboyynt"}
        view = self.production["notification_link_view"](host, None, "tiktok_live_test")
        payload = view.to_components()
        buttons = payload[0]["components"]
        self.assertEqual([b["url"] for b in buttons], ["https://www.tiktok.com/@Maboyynt/live", "https://www.tiktok.com/@Maboyynt"])
        for b in buttons:
            self.assertEqual(b["style"], 5)
            self.assertFalse(b["disabled"])
            self.assertNotIn("custom_id", b)
        self.assertIsNone(view.timeout)
        card = self.app["build_tiktok_live_embed"](host, "Maboyynt", test=True)
        self.assertEqual(card.to_dict()["author"]["url"], buttons[1]["url"])

    def test_stock_content_suppressed_custom_content_kept(self):
        host = {"platform": "tiktok", "target": "mabo_ynt", "display_name": "Atapu"}
        fn = self.production["suppress_redundant_live_content"]
        for text in ("**@mabo_ynt** sedang LIVE!", "Atapu is live!", "@mabo_ynt LIVE https://www.tiktok.com/@mabo_ynt/live"):
            self.assertIsNone(fn(host, text, "tiktok_live_test"))
        self.assertEqual(fn(host, "Ayo dukung @mabo_ynt!", "tiktok_live"), "Ayo dukung @mabo_ynt!")
        self.assertEqual(fn(host, "@mabo_ynt LIVE", "tiktok_video"), "@mabo_ynt LIVE")

    def execute(self, sql, args=()):
        with closing(self.app["db"]()) as conn:
            result = conn.execute(sql, args)
            rows = result.fetchall()
            conn.commit()
            return rows

    def new_order(self, status="pending", activated=False, deadline=None):
        now = int(time.time())
        self.execute("""INSERT INTO premium_orders(guild_id,requester_id,days,price,
            expected_amount,status,created_at,updated_at,invoice_ref,activated_at,invoice_deadline)
            VALUES(1,1,30,25000,25123,?,?,?,'TEST-INVOICE',?,?)""",
                     (status, now, now, now if activated else None, deadline))
        return {"event_id": "test-event", "invoice_ref": "TEST-INVOICE",
                "reference_id": "test-reference", "amount": 25123, "status": "paid"}

    def test_migration_repeat_preserves_data(self):
        self.production = {name: self.app[name] for name in FUNCTIONS}
        self.app["migrate_database"]()
        self.assertEqual(self.app["get_host"](1)["target"], "creator")
        self.assertEqual(self.execute("PRAGMA integrity_check")[0][0], "ok")
        self.assertTrue(self.execute("SELECT name FROM sqlite_master WHERE name='idx_notification_history_event_delivery'"))

    def test_full_backup_contains_restorable_database_and_proof(self):
        proof = Path(self.app["QRIS_STORAGE_DIR"]) / "payment-proofs" / "test.png"
        proof.parent.mkdir(parents=True)
        proof.write_bytes(b"test-proof")
        data = self.app["create_full_system_backup_zip"]()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            payload = json.loads(archive.read("config-backup.json"))
            self.assertEqual(payload["checksum_sha256"], self.app["backup_payload_checksum"](payload))
            self.assertEqual(archive.read("qris/payment-proofs/test.png"), b"test-proof")
            restored = Path(self.tmp.name) / "restored.db"
            restored.write_bytes(archive.read("database/live_notifier.db"))
        with closing(sqlite3.connect(restored)) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT target FROM hosts").fetchone()[0], "creator")

    def test_restore_preserves_premium_expiry_and_grace(self):
        expiry = int(time.time()) + 90 * 86400
        self.execute("UPDATE guild_settings SET plan='premium',premium_started_at=100,premium_expires_at=?,premium_grace_until=? WHERE guild_id=1", (expiry, expiry + 86400))
        snapshot = self.app["export_guild_backup"](1)
        self.execute("UPDATE guild_settings SET plan='free',premium_expires_at=NULL WHERE guild_id=1")
        self.app["restore_guild_backup"](snapshot, 1)
        settings = self.app["get_guild_settings"](1)
        self.assertEqual(settings["premium_expires_at"], expiry)
        self.assertEqual(settings["premium_grace_until"], expiry + 86400)
        self.assertEqual(settings["premium_started_at"], 100)

    def test_restore_rolls_back_on_sql_failure(self):
        snapshot = self.app["export_guild_backup"](1)
        snapshot["guild_config"]["youtube_channel_id"] = 123
        snapshot["hosts"][0]["display_name"] = {"invalid": "SQLite value"}
        with self.assertRaises(sqlite3.ProgrammingError):
            self.app["restore_guild_backup"](snapshot, 1)
        self.assertIsNone(self.app["get_config"](1)["youtube_channel_id"])

    def test_restore_free_limits_active_hosts(self):
        snapshot = self.app["export_guild_backup"](1)
        snapshot["hosts"] = [{"platform": "tiktok", "target": f"creator{i}"} for i in range(5)]
        self.app["restore_guild_backup"](snapshot, 1)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM hosts WHERE enabled=1")[0][0], 3)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM hosts")[0][0], 6)

    def test_full_backup_retention_across_formats(self):
        folder = Path(self.app["AUTO_BACKUP_DIR"])
        folder.mkdir()
        for i, ext in enumerate(("zip", "hnbak", "zip", "hnbak")):
            path = folder / f"hi-notifku-system-{i}.{ext}"
            path.write_bytes(b"test")
            os.utime(path, (100+i, 100+i))
        unrelated = folder / "manual-backup.zip"
        unrelated.write_bytes(b"keep")
        self.app["prune_system_backups"]()
        self.assertEqual(sorted(p.name for p in folder.glob("hi-notifku-system-*")), ["hi-notifku-system-2.zip", "hi-notifku-system-3.hnbak"])
        self.assertTrue(unrelated.exists())

    async def test_active_callback_does_not_downgrade(self):
        payload = self.new_order("active", activated=True)
        result = await self.app["process_verified_payment_event"](payload)
        self.assertTrue(result["activated"])
        self.assertEqual(self.app["get_premium_order"](1)["status"], "active")
        self.assertIsNone(self.app["get_premium_order"](1)["payment_reference"])

    async def test_closed_callbacks_cannot_reactivate(self):
        payload = self.new_order("refunded", activated=True)
        result = await self.app["process_verified_payment_event"](payload)
        self.assertFalse(result["activated"])
        self.assertEqual(self.app["get_premium_order"](1)["status"], "refunded")

    async def test_auto_off_verifies_without_activating(self):
        payload = self.new_order()
        self.app["AUTO_ACTIVATE_VERIFIED_PAYMENTS"] = False
        result = await self.app["process_verified_payment_event"](payload)
        self.assertFalse(result["activated"])
        order = self.app["get_premium_order"](1)
        self.assertEqual(order["status"], "amount_verified")
        self.assertEqual(order["amount_verified"], 1)
        self.assertIsNone(order["activated_at"])

    async def test_payment_activates_exactly_once_on_new_callback_id(self):
        payload = self.new_order()
        first = await self.app["process_verified_payment_event"](payload)
        self.assertTrue(first["activated"])
        expiry = self.app["get_guild_settings"](1)["premium_expires_at"]
        payload["event_id"] = "second-event"
        await self.app["process_verified_payment_event"](payload)
        self.assertEqual(self.app["get_guild_settings"](1)["premium_expires_at"], expiry)
        self.assertEqual(self.app["get_premium_order"](1)["status"], "active")

    async def test_late_payment_does_not_activate(self):
        payload = self.new_order(deadline=int(time.time())-10)
        result = await self.app["process_verified_payment_event"](payload)
        self.assertFalse(result["activated"])
        self.assertEqual(self.app["get_premium_order"](1)["status"], "late_payment")

    async def test_underpayment_does_not_activate(self):
        payload = self.new_order()
        payload["amount"] -= 1
        result = await self.app["process_verified_payment_event"](payload)
        self.assertFalse(result["activated"])
        self.assertEqual(self.app["get_premium_order"](1)["status"], "underpaid")

    async def test_invalid_signature_never_records_payment(self):
        from aiohttp import web
        self.app["web"] = web
        payload = self.new_order()
        request = SimpleNamespace(read=AsyncMock(return_value=json.dumps(payload).encode()),
                                  headers={"X-Payment-Timestamp": str(int(time.time())), "X-Payment-Signature": "invalid"})
        response = await self.app["payment_webhook_handler"](request)
        self.assertEqual(response.status, 401)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM payment_callback_events")[0][0], 0)
        self.assertEqual(self.app["get_premium_order"](1)["status"], "pending")

    async def test_callback_rejects_invalid_amount_and_long_id(self):
        payload = self.new_order()
        for amount in (-1, True, 25123.9):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    await self.app["process_verified_payment_event"]({**payload, "amount": amount})
        with self.assertRaises(ValueError):
            await self.app["process_verified_payment_event"]({**payload, "event_id": "x"*161})

    async def test_partial_delivery_retries_only_failed_channel(self):
        first = AsyncMock(return_value=SimpleNamespace(id=101))
        second = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
        channels = {10: SimpleNamespace(send=first), 20: SimpleNamespace(send=second)}
        self.app["resolve_channel"] = AsyncMock(side_effect=lambda i: channels[i])
        ok = await self.app["send_notification"](self.host, Embed(), event_type="tiktok_live", event_key="live-1")
        self.assertTrue(ok)  # Accepted into durable retry queue.
        self.assertEqual(self.execute("SELECT COUNT(*) FROM pending_notifications")[0][0], 1)
        second.side_effect = None
        second.return_value = SimpleNamespace(id=102)
        self.execute("UPDATE pending_notifications SET release_after=0")
        self.app["claim_pending_notification"] = Mock(return_value=True)
        await self.app["pending_notification_loop"]()
        self.assertEqual(first.await_count, 1)
        self.assertEqual(second.await_count, 2)
        self.assertEqual(self.execute("SELECT COUNT(*) FROM pending_notifications")[0][0], 0)

    async def test_emergency_holds_new_events_and_queue_without_retries(self):
        self.app["runtime_setting_enabled"] = Mock(return_value=True)
        self.app["resolve_channel"] = AsyncMock()
        self.assertTrue(await self.app["send_notification"](self.host, Embed(), event_key="emergency"))
        self.execute("UPDATE pending_notifications SET release_after=0")
        await self.app["pending_notification_loop"]()
        self.app["resolve_channel"].assert_not_awaited()
        self.assertEqual(self.execute("SELECT retry_count FROM pending_notifications")[0][0], 0)

    async def test_tiktok_two_sessions_without_metadata_both_notify(self):
        live = AsyncMock(side_effect=[True, False, True])
        self.app.update({
            "TikTokLiveClient": lambda **kw: SimpleNamespace(is_live=live),
            "record_api_call": Mock(), "check_tiktok_live_fallback": AsyncMock(return_value=None),
            "build_tiktok_live_embed": Mock(return_value=Embed()), "render_template": Mock(return_value=None),
            "premium_host_template": Mock(return_value=None), "maybe_send_live_end": AsyncMock(),
            "send_notification": AsyncMock(return_value=True),
        })
        await self.app["check_tiktok_live"](self.host)
        await self.app["check_tiktok_live"](self.host)
        await self.app["check_tiktok_live"](self.host)
        calls = self.app["send_notification"].await_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].kwargs["event_key"], calls[1].kwargs["event_key"])

    async def test_webhook_fallback_primary_is_not_resent_on_retry(self):
        self.execute("UPDATE hosts SET webhook_url='https://discord.com/api/webhooks/test' WHERE id=1")
        host = self.app["get_host"](1)
        webhook = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("webhook failed")))
        self.app["discord"].Webhook = SimpleNamespace(from_url=Mock(return_value=webhook))
        self.app["http"] = SimpleNamespace(closed=False)
        first = AsyncMock(return_value=SimpleNamespace(id=101))
        second = AsyncMock(side_effect=RuntimeError("extra channel failed"))
        channels = {10: SimpleNamespace(send=first), 20: SimpleNamespace(send=second)}
        self.app["resolve_channel"] = AsyncMock(side_effect=lambda i: channels[i])
        self.assertFalse(await self.app["_deliver_notification_now"](host, Embed(), None,
            event_type="test", event_key="webhook-fallback", source_url=None))
        second.side_effect = None
        second.return_value = SimpleNamespace(id=102)
        self.assertTrue(await self.app["_deliver_notification_now"](host, Embed(), None,
            event_type="test", event_key="webhook-fallback", source_url=None, skip_sent=True))
        self.assertEqual(webhook.send.await_count, 1)
        self.assertEqual(first.await_count, 1)

    async def test_tiktok_username_metadata_is_not_a_room_id(self):
        live = AsyncMock(side_effect=[True, False, True])
        self.app.update({
            "TikTokLiveClient": lambda **kw: SimpleNamespace(is_live=live),
            "record_api_call": Mock(), "check_tiktok_live_fallback": AsyncMock(return_value={"id": "creator"}),
            "build_tiktok_live_embed": Mock(return_value=Embed()), "render_template": Mock(return_value=None),
            "premium_host_template": Mock(return_value=None), "maybe_send_live_end": AsyncMock(),
            "send_notification": AsyncMock(return_value=True),
        })
        for _ in range(3):
            await self.app["check_tiktok_live"](self.host)
        calls = self.app["send_notification"].await_args_list
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0].kwargs["event_key"], calls[1].kwargs["event_key"])

    async def test_cleanup_preserves_receipts_for_pending_retry(self):
        self.app["record_notification_history"](guild_id=1, host_id=1, event_type="test", event_key="pending",
            channel_id=10, message_id=1, status="sent", latency_ms=1, source_url=None,
            title="test", content=None, embed=Embed())
        self.app["queue_notification_retry"](self.host, Embed(), None, event_type="test", event_key="pending", source_url=None)
        self.execute("UPDATE notification_history SET created_at=0")
        await self.app["event_cleanup_loop"]()
        self.assertEqual(self.execute("SELECT COUNT(*) FROM notification_history")[0][0], 1)

    async def test_webhook_can_resume_received_event_and_reject_conflict(self):
        from aiohttp import web
        self.app["web"] = web
        self.app["AUTO_ACTIVATE_VERIFIED_PAYMENTS"] = False
        payload = self.new_order()
        body = json.dumps(payload).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(b"offline-test-secret", timestamp.encode()+b"."+body, hashlib.sha256).hexdigest()
        request = SimpleNamespace(read=AsyncMock(return_value=body), headers={"X-Payment-Timestamp": timestamp, "X-Payment-Signature": signature})
        self.app["record_payment_callback_event"](event_id=payload["event_id"], invoice_ref=payload["invoice_ref"],
            reference_id=payload["reference_id"], amount=payload["amount"], payment_status="paid",
            payload_hash=hashlib.sha256(body).hexdigest(), signature_valid=True)
        response = await self.app["payment_webhook_handler"](request)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.app["get_premium_order"](1)["status"], "amount_verified")
        duplicate = await self.app["payment_webhook_handler"](request)
        self.assertTrue(json.loads(duplicate.body)["duplicate"])
        self.execute("UPDATE payment_callback_events SET payload_hash='different'")
        conflict = await self.app["payment_webhook_handler"](request)
        self.assertEqual(conflict.status, 409)


if __name__ == "__main__":
    unittest.main()
