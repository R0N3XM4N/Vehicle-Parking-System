"""Exercise the story demo through real Chromium at three viewport sizes."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from threading import Thread
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from app import create_app, db
from app.models import User


def run():
    output = Path("test-results/browser")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        app = create_app(
            {
                "TESTING": True,
                "BCRYPT_ROUNDS": 4,
                "SECRET_KEY": "browser-test-secret-only",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{Path(temporary)/'browser.db'}",
            }
        )
        app.logger.disabled = True
        with app.app_context():
            admin = User(
                name="Demo Admin", email="browser-admin@example.com", role="admin"
            )
            admin.set_password("Browser-test-123")
            db.session.add(admin)
            db.session.commit()
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    for index, (width, height) in enumerate(
                        ((1200, 800), (768, 900), (390, 844))
                    ):
                        context = browser.new_context(
                            viewport={"width": width, "height": height}
                        )
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("dialog", lambda dialog: dialog.accept())

                        def check(label):
                            assert page.locator("main h1").is_visible(), label
                            assert page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            ), f"Overflow at {label}/{width}"
                            assert not errors, errors
                            page.screenshot(
                                path=str(output / f"{width}-{label}.png"),
                                full_page=True,
                            )

                        page.goto(base + "/register")
                        page.locator('[name="name"]').fill("Demo Driver")
                        page.locator('[name="email"]').fill(
                            f"browser-{index}@example.com"
                        )
                        page.locator('[name="password"]').fill("Browser-test-123")
                        page.get_by_role("button", name="Create account").click()
                        assert page.url.endswith("/login")
                        page.locator('[name="email"]').fill(
                            f"browser-{index}@example.com"
                        )
                        page.locator('[name="password"]').fill("Browser-test-123")
                        page.get_by_role("button", name="Log in", exact=True).click()
                        page.goto(base + "/parking")
                        check("parking")
                        page.locator('a[href^="/reserve/"]').first.click()
                        page.locator('[name="vehicle_number"]').fill("KA01AB1234")
                        now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(
                            second=0, microsecond=0
                        )
                        page.locator('[name="start_time"]').fill(
                            now.strftime("%Y-%m-%dT%H:%M")
                        )
                        page.locator('[name="end_time"]').fill(
                            (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                        )
                        page.get_by_role(
                            "button", name="Review and Confirm Reservation"
                        ).click()
                        assert (
                            "Reserved"
                            in page.locator(".reservation-card").first.inner_text()
                        )
                        watcher = None
                        if index == 0:
                            watcher = context.new_page()
                            watcher.goto(base + "/parking")
                            expect(
                                watcher.locator("[data-occupancy] tbody tr")
                                .first.locator("td")
                                .nth(3)
                            ).to_have_text("1")
                        page.get_by_role("button", name="Record Vehicle Entry").click()
                        if watcher:
                            watcher.bring_to_front()
                            expect(
                                watcher.locator("[data-occupancy] tbody tr")
                                .first.locator("td")
                                .nth(4)
                            ).to_have_text("1", timeout=20000)
                            watcher.close()
                            page.bring_to_front()
                        page.get_by_role("link", name="Preview Fee and Exit").click()
                        check("fee-preview")
                        amount = page.locator(".summary-total dd").inner_text()
                        page.get_by_role(
                            "button", name="Confirm Exit and Continue to Payment"
                        ).click()
                        page.get_by_role("button", name="Pay ").click()
                        assert amount in page.locator(".receipt-card").inner_text()
                        check("receipt")
                        page.get_by_role("button", name="Log out").click()
                        page.goto(base + "/parking")
                        assert page.url.endswith("/login")
                        page.locator('[name="email"]').fill("browser-admin@example.com")
                        page.locator('[name="password"]').fill("Browser-test-123")
                        page.get_by_role("button", name="Log in", exact=True).click()
                        page.goto(base + "/admin")
                        check("admin")
                        rate_form = page.locator(
                            'form[action="/admin/rates/update"]'
                        ).filter(has=page.locator('input[value="four-wheeler"]'))
                        rate_form.locator('[name="hourly_rate"]').fill("45.50")
                        rate_form.get_by_role("button", name="Update type rate").click()
                        assert (
                            rate_form.locator('[name="hourly_rate"]').input_value()
                            == "45.50"
                        )
                        page.goto(base + "/admin/audit")
                        check("audit")
                        assert "KA01AB1234" in page.locator("main").inner_text()
                        results.append(
                            dict(
                                width=width,
                                height=height,
                                result="pass",
                                flows=[
                                    "registration",
                                    "login",
                                    "reserve",
                                    "entry",
                                    "fee-preview",
                                    "exit",
                                    "payment",
                                    "receipt",
                                    "logout",
                                    "type-rate-update",
                                    "admin-audit",
                                ],
                                page_errors=errors,
                            )
                        )
                        context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
    (output / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run()
