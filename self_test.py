import os
import re
import ast
import tempfile
from pathlib import Path

tmp = tempfile.NamedTemporaryFile(prefix="hi-notifku-test-", suffix=".db", delete=False)
tmp.close()

os.environ["DB_PATH"] = tmp.name
os.environ.setdefault("DISCORD_TOKEN", "")
os.environ.setdefault("OWNER_IDS", "1")

import bot as app

errors = []

try:
    app.migrate_database()
except Exception as exc:
    errors.append(f"migration: {type(exc).__name__}: {exc}")

source = Path(app.__file__).read_text(encoding="utf-8")

try:
    tree = ast.parse(source)
    classes = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    view_refs = set(re.findall(r"\b([A-Z][A-Za-z0-9_]+View)\(", source))
    missing = sorted(x for x in view_refs if x not in classes)
    if missing:
        errors.append("missing views: " + ", ".join(missing))
except Exception as exc:
    errors.append(f"ast: {type(exc).__name__}: {exc}")

if source.count("async def on_message(") != 1:
    errors.append("on_message count != 1")

if source.count("async def on_ready(") != 1:
    errors.append("on_ready count != 1")

command_names = {
    cmd.name
    for cmd in app.bot.tree.get_commands()
}
expected = {"ping", "start", "menu", "owner"}
if command_names != expected:
    errors.append(
        "slash commands mismatch: "
        + repr(sorted(command_names))
    )

view_factories = [
    ("StartVerifyView", lambda: app.StartVerifyView()),
    ("PaymentSettingsView", lambda: app.PaymentSettingsView()),
    ("OwnerHomeView", lambda: app.OwnerHomeView()),
    ("DMUserGuildPickerView", lambda: app.DMUserGuildPickerView(123)),
    ("ServerBrowserView", lambda: app.ServerBrowserView()),
    ("ServerOwnerView", lambda: app.ServerOwnerView(123)),
    ("HostMenuView", lambda: app.HostMenuView(123)),
    ("HostBrowserView", lambda: app.HostBrowserView(123)),
    ("PremiumOrdersView", lambda: app.PremiumOrdersView()),
    ("RevenueReportView", lambda: app.RevenueReportView()),
    ("HealthDetailView", lambda: app.HealthDetailView()),
]

for name, factory in view_factories:
    try:
        factory()
    except Exception as exc:
        errors.append(f"{name}: {type(exc).__name__}: {exc}")

try:
    order_id = app.create_premium_order(
        guild_id=987654321,
        requester_id=123456789,
        days=30,
        price=25000
    )
    order = app.get_premium_order(order_id)

    if not order:
        errors.append("order creation returned no row")
    else:
        ref = app.ensure_invoice_ref(order_id)
        if not ref.startswith("INV-"):
            errors.append("invoice ref invalid")

        if int(order["expected_amount"]) <= int(order["price"]):
            errors.append("unique payment amount invalid")

        if app.Image is not None:
            image = app.invoice_image_bytes(
                app.get_premium_order(order_id)
            )
            if not image.startswith(b"\x89PNG"):
                errors.append("invoice PNG invalid")
except Exception as exc:
    errors.append(f"premium order: {type(exc).__name__}: {exc}")

try:
    app.database_maintenance()
except Exception as exc:
    errors.append(f"maintenance: {type(exc).__name__}: {exc}")

if errors:
    print("SELF TEST: FAIL")
    for item in errors:
        print(" -", item)
    raise SystemExit(1)

print("SELF TEST: PASS")
print("Commands:", ", ".join(sorted(command_names)))
print("Views checked:", len(view_factories))
