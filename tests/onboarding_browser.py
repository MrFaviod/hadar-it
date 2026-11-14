#!/usr/bin/env python3
"""Real-browser proof of the onboarding wizard against the disposable stack.

``tests/onboarding_e2e.py --browser`` starts the compose project and runs this
script in two phases, because the operator's database step sits between them:
the API must not exist while the database is being prepared, exactly like the
documented installation.

    phase setup   claim, AI provider (fixture) or explicit defer, storage check
                  and apply. Ends on the first-owner panel and saves the
                  browser storage state (the HttpOnly setup session cookie).
    phase finish  first owner, configuration sections, verification, report,
                  finish and the hand-over to the normal application.

The same browser profile is reused, so the setup session survives the pause;
it is a cookie scoped to ``/api/setup/v1`` and is never read by the page.

Secrets arrive through the environment (never argv): SETUP_CLAIM_CREDENTIAL,
SETUP_DATABASE_URL, AI_FIXTURE_KEY, SETUP_OWNER_PASSWORD.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - environment guard
    print("BLOCKED: playwright is not installed for this interpreter", file=sys.stderr)
    raise SystemExit(2)

TEXT = {
    "en": {
        "claim": "Initial setup",
        "claimed": "Installation claimed",
        "ai": "AI provider",
        "storage": "Database",
        "owner": "First administrator account",
        "configure": "Installation configuration",
        "finish": "Installation ready to finish",
        "complete": "Installation complete",
    },
    "es": {
        "claim": "Configuración inicial",
        "claimed": "Instalación reclamada",
        "ai": "Proveedor de IA",
        "storage": "Base de datos",
        "owner": "Primera cuenta de administración",
        "configure": "Configuración de la instalación",
        "finish": "Instalación lista para finalizar",
        "complete": "Instalación completada",
    },
}
FORBIDDEN_REPORT_TOKENS = ("password", "contraseña", "secret", "secreto", "token", "api_key", "database_url")
# The boot probe deliberately asks the two anonymous endpoints before the stack
# is complete; those refusals are the expected answer, not a page defect.
EXPECTED_RESOURCE_ERRORS = (
    "Failed to load resource: the server responded with a status of 401",
    "Failed to load resource: the server responded with a status of 404",
    "Failed to load resource: net::ERR_ABORTED",
    # A blocked verification is the documented answer: the wizard renders the
    # blocking checklist, so the 409 is a state transition, not a page defect.
    "Failed to load resource: the server responded with a status of 409",
)


class Failure(AssertionError):
    pass


class Run:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.evidence = Path(options.evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.checks = 0
        self.shots: list[str] = []
        self.console: list[str] = []
        self.page_errors: list[str] = []
        self.http_errors: list[str] = []
        self.notes: list[str] = []
        self.headings = TEXT[options.locale]

    # ------------------------------------------------------------- assertions
    def check(self, condition: object, message: str) -> None:
        if not condition:
            raise Failure(message)
        self.checks += 1

    def note(self, message: str) -> None:
        self.notes.append(message)
        print(f"NOTE {message}")

    def shot(self, page, name: str) -> None:
        index = len(self.shots) + 1
        path = self.evidence / f"{index:02d}-{name}.png"
        page.screenshot(path=str(path), full_page=True)
        self.shots.append(str(path))
        print(f"SHOT {path}")

    def expect_heading(self, page, selector: str, key: str) -> None:
        expect(page.locator(selector)).to_contain_text(self.headings[key], timeout=30000)
        self.checks += 1

    # ------------------------------------------------------------ error traps
    def attach(self, page) -> None:
        page.on(
            "pageerror",
            lambda error: self.page_errors.append(str(error)[:400]),
        )

        def console(message) -> None:
            if message.type != "error":
                return
            text = message.text[:400]
            if any(token in text for token in EXPECTED_RESOURCE_ERRORS):
                return
            location = (message.location or {}).get("url", "")
            if "/api/v1/health/" in location and "status of 50" in text:
                return
            self.console.append(text)

        page.on("console", console)

        def response(event) -> None:
            status = event.status
            if status < 500:
                return
            path = event.url.split("://", 1)[-1]
            path = path.split("/", 1)[-1]
            if path.startswith("api/v1/health/"):
                return
            self.http_errors.append(f"{status} {event.url[:200]}")

        page.on("response", response)

    def unexpected_errors(self) -> list[str]:
        return [
            *(f"pageerror: {item}" for item in self.page_errors),
            *(f"console: {item}" for item in self.console),
            *(f"http: {item}" for item in self.http_errors),
        ]

    # ----------------------------------------------------------------- phases
    def phase_setup(self, page, context) -> None:
        o = self.options
        credential = os.environ.get("SETUP_CLAIM_CREDENTIAL", "")
        if not credential:
            raise SystemExit("BLOCKED: SETUP_CLAIM_CREDENTIAL is required for phase setup")
        database_url = os.environ.get("SETUP_DATABASE_URL", "")
        if not database_url:
            raise SystemExit("BLOCKED: SETUP_DATABASE_URL is required for phase setup")

        page.goto(o.base_url, wait_until="domcontentloaded")
        page.wait_for_selector('[data-setup-wizard="claim"]', timeout=60000)
        self.expect_heading(page, "#setup-title", "claim")
        self.shot(page, "claim")

        page.locator("#setup-credential").fill(credential)
        page.locator("#setup-claim-submit").click()
        page.wait_for_selector('[data-setup-wizard="claimed"]', timeout=60000)
        self.expect_heading(page, "#setup-title", "claimed")
        expect(page.locator("[data-setup-state]").first).to_have_text("claimed", timeout=15000)
        self.checks += 1
        self.shot(page, "claimed")

        # AI: the fixture provider is a real OpenAI-compatible endpoint reached
        # through the setup service. Without one, the explicit defer is the path.
        page.wait_for_selector('[data-setup-panel="ai"]', timeout=30000)
        self.expect_heading(page, "#setup-ai-title", "ai")
        if o.ai_base_url:
            page.locator("#setup-ai-base-url").fill(o.ai_base_url)
            page.locator("#setup-ai-model").fill(o.ai_model)
            page.locator("#setup-ai-api-key").fill(os.environ.get("AI_FIXTURE_KEY", ""))
            page.locator("#setup-ai-verify").click()
            page.wait_for_selector('[data-setup-ai="configured"]', timeout=180000)
            expect(page.locator('[data-setup-receipt="provider"]')).to_contain_text(
                o.ai_provider, timeout=15000
            )
            expect(page.locator('[data-setup-receipt="model"]')).to_contain_text(
                o.ai_model, timeout=15000
            )
            expect(page.locator('[data-setup-receipt="tool"]')).to_have_text(
                "get_setup_status", timeout=15000
            )
            self.checks += 3
            self.shot(page, "ai-configured")
            page.locator("#setup-ai-continue").click()
        else:
            page.locator("#setup-ai-defer").click()
            page.wait_for_selector('[data-setup-ai="deferred"]', timeout=30000)
            self.check(
                page.locator("[data-setup-state]").first.inner_text() == "ai_deferred",
                "deferring leaves the installation in ai_deferred",
            )
            self.shot(page, "ai-deferred")

        page.wait_for_selector('[data-setup-panel="storage"]', timeout=30000)
        self.expect_heading(page, "#setup-storage-title", "storage")
        engine = os.environ.get("SETUP_DATABASE_ENGINE", "sqlite")
        radio = "postgres" if engine.startswith("postgres") else "sqlite"
        page.locator(f"#setup-storage-engine-{radio}").check(force=True)
        self.check(
            page.locator(f"#setup-storage-engine-{radio}").is_checked(),
            f"the {radio} engine is selected",
        )
        page.locator("#setup-storage-url").fill(database_url)
        page.locator("#setup-storage-check").click()
        page.wait_for_selector("[data-setup-storage-probe]", timeout=90000)
        probe_class = page.get_attribute("[data-setup-storage-probe]", "data-setup-probe-class")
        self.check(
            probe_class in ("empty", "ours"),
            f"the probe classifies the database as adoptable (got {probe_class!r})",
        )
        self.shot(page, "storage-probe")

        expect(page.locator("#setup-storage-apply")).to_be_enabled(timeout=15000)
        page.locator("#setup-storage-apply").click()
        page.wait_for_selector('[data-setup-panel="owner"]', timeout=300000)
        self.check(
            page.locator("[data-setup-state]").first.inner_text() == "storage_ready",
            "applying the database reports storage_ready",
        )
        self.shot(page, "owner-panel")
        context.storage_state(path=o.save_storage_state)

    def phase_finish(self, page, context) -> None:
        o = self.options
        password = os.environ.get("SETUP_OWNER_PASSWORD", "")
        if not password:
            raise SystemExit("BLOCKED: SETUP_OWNER_PASSWORD is required for phase finish")

        page.goto(o.base_url, wait_until="domcontentloaded")
        page.wait_for_selector('[data-setup-panel="owner"]', timeout=60000)
        self.expect_heading(page, "#setup-owner-title", "owner")
        self.shot(page, "resumed-owner")

        page.locator("#setup-owner-username").fill(o.owner_username)
        page.locator("#setup-owner-display-name").fill(o.owner_display_name)
        page.locator("#setup-owner-email").fill(o.owner_email)
        page.locator("#setup-owner-password").fill(password)
        page.locator("#setup-owner-confirm").fill(password)
        page.locator("#setup-owner-submit").click()
        page.wait_for_selector('[data-setup-owner="created"]', timeout=180000)
        expect(page.locator('[data-setup-owner-field="username"]')).to_have_text(
            o.owner_username, timeout=15000
        )
        self.checks += 1
        self.check(password not in page.content(), "the owner password is not kept in the document")
        self.shot(page, "owner-created")

        page.wait_for_selector('[data-setup-panel="configure"]', timeout=60000)
        self.expect_heading(page, "#setup-config-title", "configure")
        page.wait_for_selector('[data-setup-section="agent"]', timeout=90000)
        self.check(
            page.locator("[data-setup-section]").count() >= 5,
            "every configuration section is listed",
        )
        self.shot(page, "configuration")

        self.change_appearance(page)
        self.apply_agent(page)
        self.postpone_notifications(page)
        self.shot(page, "configured")

        # Verification is the service's own checklist. Production withholds the
        # backup decision until the first checklist names it, so a refused run
        # may offer the risk item and then be verified again once it is decided.
        self.verify(page, attempts=2)
        self.expect_heading(page, "#setup-finish-title", "finish")
        page.wait_for_selector("[data-setup-finish-report]", timeout=60000)
        self.check(
            page.locator("[data-setup-finish-field]").count() >= 6,
            "the sanitized installation report is rendered",
        )
        report_text = page.locator("[data-setup-finish-report]").inner_text().lower()
        leaked = [token for token in FORBIDDEN_REPORT_TOKENS if token in report_text]
        self.check(not leaked, f"the report keeps no credential material (found {leaked})")
        self.shot(page, "finish-report")

        with page.expect_download() as download_info:
            page.locator("#setup-finish-download").click()
        download = download_info.value
        payload = json.loads(Path(download.path()).read_text(encoding="utf-8"))
        self.check(
            payload.get("contract") == "onboarding/v1",
            f"the exported report carries the onboarding contract (got {payload.get('contract')!r})",
        )
        serialized = json.dumps(payload).lower()
        self.check(
            not any(token in serialized for token in ("password", "api_key", "database_url", "token")),
            "the exported report keeps no credential material",
        )

        page.locator("#setup-finish-confirm").click()
        page.wait_for_selector("[data-setup-complete]", timeout=180000)
        self.expect_heading(page, "[data-setup-complete-heading]", "complete")
        self.check(
            page.locator('[data-setup-complete-link]').get_attribute("href") == "/",
            "the completed screen links to the application",
        )
        self.check(page.locator("[data-setup-wizard]").count() == 0, "the wizard unmounts on completion")
        self.shot(page, "complete")

        # Reload: the normal application must render, never the wizard again.
        page.goto(o.base_url, wait_until="domcontentloaded")
        expect(page.locator(".login").first).to_be_visible(timeout=60000)
        self.checks += 1
        self.check(page.locator("[data-setup-wizard]").count() == 0, "a reload does not remount the wizard")
        self.check(page.locator("[data-setup-complete]").count() == 0, "the completed screen is not sticky")
        self.shot(page, "app-after-complete")

        # In-page fetch: Chromium owns the host mapping and the TLS trust for the edge.
        ready = page.evaluate(
            """async () => {
                const response = await fetch('/api/v1/health/ready',
                  {credentials: 'same-origin', cache: 'no-store'});
                let body = {};
                try { body = await response.json(); } catch (error) { body = {}; }
                return {status: response.status, body};
            }"""
        )
        body = ready.get("body") or {}
        self.check(ready["status"] == 200, f"the API is ready after completion (got {ready['status']})")
        self.check(
            body.get("installation_complete") is True,
            "the API reports the installation complete",
        )
        self.check(not body.get("setup_enabled", False), "setup is closed after completion")

    # ------------------------------------------------------------ interactions
    def change_appearance(self, page) -> None:
        selector = "#setup-config-input-appearance"
        values = [value for value in page.locator(f"{selector} option").evaluate_all(
            "options => options.map(option => option.value)"
        ) if value]
        current = page.locator(selector).input_value()
        target = next((value for value in values if value != current), "")
        if not target:
            self.note("appearance: the only preset is already active; the section was left unchanged")
            return
        page.select_option(selector, target)
        organization = page.locator("#setup-config-input-appearance-organizationName")
        if organization.count() == 1:
            organization.fill(self.options.organization_name)
        else:
            self.note("appearance: no organization name input was rendered")
        page.locator('[data-setup-config-preview-submit="appearance"]').click()
        page.wait_for_selector('[data-setup-config-preview="appearance"]', timeout=60000)
        preview_text = page.locator('[data-setup-config-preview="appearance"]').inner_text()
        self.check(
            "→" in preview_text,
            "the appearance preview lists the proposed change",
        )
        if organization.count() == 1:
            self.check(
                self.options.organization_name in preview_text,
                "the appearance preview carries the organization name",
            )
        page.locator('[data-setup-config-apply="appearance"]').click()
        page.wait_for_selector('[data-setup-config-receipt="appearance"]', timeout=120000)
        self.check(
            page.locator('[data-setup-config-receipt="appearance"] [data-setup-config-receipt-status="passed"]').count() == 1,
            "the appearance change reads back as passed",
        )
        self.check(
            page.locator('[data-setup-section="appearance"][data-setup-section-status="passed"]').count() == 1,
            "the appearance section turns green",
        )
        if organization.count() == 1:
            current_block = page.locator('[data-setup-config-current="appearance"]')
            # The receipt paints first; the section re-read lands after it.
            try:
                expect(current_block).to_contain_text(self.options.organization_name, timeout=20000)
            except PlaywrightTimeoutError:
                pass
            self.check(
                current_block.count() == 1
                and self.options.organization_name in current_block.inner_text(),
                "the applied organization name reads back",
            )
        self.shot(page, "appearance-applied")

    def apply_agent(self, page) -> None:
        page.locator("#setup-config-input-agent-provider").fill("openai")
        page.locator("#setup-config-input-agent-model").fill(self.options.ai_model)
        page.locator('[data-setup-config-preview-submit="agent"]').click()
        page.wait_for_selector('[data-setup-config-preview="agent"]', timeout=60000)
        page.locator('[data-setup-config-apply="agent"]').click()
        page.wait_for_selector('[data-setup-config-receipt="agent"]', timeout=240000)
        status = page.locator('[data-setup-config-receipt="agent"] [data-setup-config-receipt-status]')
        if status.count() != 1:
            raise Failure("the agent section rendered no receipt status")
        observed = status.first.inner_text().strip().lower()
        self.check(
            observed in ("passed", "aprobado"),
            f"the agent probe passes through the UI (got {observed!r})",
        )
        record = page.locator("[data-setup-provider-record]")
        if record.count() == 1:
            # The receipt paints first and the section re-read lands after it,
            # so the record line turns "true" one render behind the receipt.
            try:
                page.wait_for_selector('[data-setup-provider-record="true"]', timeout=20000)
                linked = "true"
            except PlaywrightTimeoutError:
                linked = record.first.get_attribute("data-setup-provider-record")
            self.check(
                linked == "true",
                f"the agent section links the verified provider as a record (got {linked!r})",
            )
        self.shot(page, "agent-verified")

    def verify(self, page, attempts: int = 2) -> None:
        for attempt in range(1, attempts + 1):
            page.locator("#setup-verify-submit").click()
            try:
                page.wait_for_selector(
                    '[data-setup-finish], [data-setup-config="blocked"], [data-setup-config="verify-error"]',
                    timeout=300000,
                )
            except PlaywrightTimeoutError:
                panel = page.locator('[data-setup-panel="configure"]')
                detail = " ".join(panel.inner_text().split())[:500] if panel.count() else "no configure panel"
                raise Failure(f"verification left the wizard without a finish step: {detail}") from None
            if page.locator("[data-setup-finish]").count() == 1:
                self.checks += 1
                self.shot(page, "verified")
                return
            blocked = page.locator('[data-setup-config="blocked"], [data-setup-config="verify-error"]')
            detail = " ".join(blocked.first.inner_text().split())[:600] if blocked.count() else ""
            self.note(f"verification attempt {attempt} is blocked: {detail[:300]}")
            if page.locator("[data-setup-backup-form]").count() == 1:
                self.declare_backup_policy(page)
                continue
            if page.locator('[data-setup-config-risk="operational"]').count() == 1:
                self.accept_backup_risk(page)
                continue
            raise Failure(f"verification is blocked and offers no decision: {detail}")
        raise Failure("verification is still blocked after the offered decision was recorded")

    def postpone_notifications(self, page) -> None:
        button = page.locator('[data-setup-config-postpone="notifications"]')
        if button.count() == 0:
            self.note("notifications: the section is not postponable in this mode")
            return
        button.click()
        page.wait_for_selector(
            '[data-setup-section="notifications"][data-setup-section-status="postponed"]',
            timeout=60000,
        )
        self.check(
            page.locator('[data-setup-section="notifications"][data-setup-section-status="passed"]').count() == 0,
            "a postponed section is never painted as passed",
        )

    def declare_backup_policy(self, page) -> None:
        """State the production backup policy; the wizard must answer 'declared'."""
        if page.locator("[data-setup-backup-form]").count() == 0:
            self.note("operational: the declaration form is not rendered")
            return
        for field, value in (
            ("target", "s3://e2e-backups/prod"),
            ("schedule", "daily 02:00 UTC"),
            ("retention", "30 days"),
            ("responsible", "platform team"),
        ):
            page.locator(f"#setup-backup-{field}").fill(value)
        page.select_option("#setup-backup-location_kind", "object_storage")
        with page.expect_response(
            lambda response: "/configuration/operational" in response.url
            and response.request.method == "POST"
        ) as preview:
            page.locator("[data-setup-backup-preview]").click()
        self.check(
            preview.value.status == 200,
            f"the declaration preview answers 200 (got {preview.value.status})",
        )
        try:
            page.wait_for_selector("[data-setup-backup-diff]", timeout=30000)
        except PlaywrightTimeoutError as exc:
            self.shot(page, "backup-preview-missing")
            raise Failure(
                "the declaration preview renders no diff although the service "
                "answered 200: the page keys on proposed.item, which the "
                "operational preview body does not carry"
            ) from exc
        self.check(
            "→" in page.locator("[data-setup-backup-diff]").inner_text(),
            "the declaration preview lists the stated policy",
        )
        page.locator("[data-setup-backup-declare]").click()
        page.wait_for_selector("[data-setup-backup-readback]", timeout=120000)
        self.check(
            page.locator('[data-setup-section="operational"][data-setup-section-status="declared"]').count() == 1,
            "the operational section reads back as declared",
        )
        self.check(
            page.locator('[data-setup-section="operational"][data-setup-section-status="passed"]').count() == 0,
            "a declaration is never painted as passed",
        )
        self.shot(page, "backup-declared")

    def accept_backup_risk(self, page) -> None:
        risk = page.locator('[data-setup-config-risk="operational"]')
        if risk.count() == 0:
            self.note("operational: no production risk item was offered")
            return
        page.locator("#setup-config-risk-reason-operational").fill(
            "browser e2e accepts the disposable backup risk"
        )
        page.check("#setup-config-risk-confirm-operational")
        page.locator('[data-setup-config-risk-accept="operational"]').click()
        try:
            page.wait_for_selector(
                '[data-setup-section="operational"][data-setup-section-status="risk"]',
                timeout=60000,
            )
        except PlaywrightTimeoutError:
            self.note("operational: the section chip did not turn to risk within 60s")
        self.shot(page, "backup-risk-accepted")


def browser_launch(playwright, options: argparse.Namespace):
    args = []
    if options.resolve:
        host, address = options.resolve.split("=", 1)
        args.append(f"--host-resolver-rules=MAP {host} {address}")
    if options.base_url.startswith("https://"):
        args.append("--ignore-certificate-errors")
    return playwright.chromium.launch(headless=True, args=args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drive the onboarding wizard in Chromium.")
    parser.add_argument("--phase", choices=("setup", "finish"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--mode", choices=("dev", "prod"), default="dev")
    parser.add_argument("--locale", choices=("en", "es"), default="en")
    parser.add_argument("--storage-state", default="")
    parser.add_argument("--save-storage-state", default="")
    parser.add_argument("--resolve", default="", help="host=address for a disposable TLS edge")
    parser.add_argument("--ai-base-url", default="")
    parser.add_argument("--ai-model", default="probe-model")
    parser.add_argument("--ai-provider", default="ai-fixture")
    parser.add_argument("--owner-username", default="owner")
    parser.add_argument("--owner-display-name", default="Installation Owner")
    parser.add_argument("--owner-email", default="owner@example.invalid")
    parser.add_argument("--organization-name", default="E2E Installation")
    options = parser.parse_args(argv)
    if options.phase == "finish" and not options.storage_state:
        parser.error("--storage-state is required for phase finish")
    if options.phase == "setup" and not options.save_storage_state:
        parser.error("--save-storage-state is required for phase setup")

    run = Run(options)
    status = "failed"
    error = ""
    try:
        with sync_playwright() as playwright:
            browser = browser_launch(playwright, options)
            kwargs = {
                "viewport": {"width": 1440, "height": 1000},
                "locale": "es-ES" if options.locale == "es" else "en-US",
                "accept_downloads": True,
                "ignore_https_errors": options.base_url.startswith("https://"),
            }
            if options.storage_state:
                kwargs["storage_state"] = options.storage_state
            context = browser.new_context(**kwargs)
            context.add_init_script(
                f"try {{ localStorage.setItem('itsm.locale', '{options.locale}'); }} catch (e) {{}}"
            )
            page = context.new_page()
            page.set_default_timeout(20000)
            run.attach(page)
            if options.phase == "setup":
                run.phase_setup(page, context)
            else:
                run.phase_finish(page, context)
            errors = run.unexpected_errors()
            run.check(not errors, "the page raised no error: " + "; ".join(errors[:4]))
            context.close()
            browser.close()
        status = "passed"
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - the failure text is the report
        error = f"{exc.__class__.__name__}: {str(exc)[:800]}"
    finally:
        summary = {
            "phase": options.phase,
            "mode": options.mode,
            "base_url": options.base_url,
            "status": status,
            "error": error,
            "checks": run.checks,
            "screenshots": run.shots,
            "notes": run.notes,
            "page_errors": run.page_errors,
            "console_errors": run.console,
            "http_errors": run.http_errors,
        }
        path = Path(options.evidence) / f"{options.phase}.json"
        path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"SUMMARY {path}")

    if status != "passed":
        print(f"FAIL browser {options.phase}: {error or 'a wizard assertion failed'}", file=sys.stderr)
        return 1
    print(
        f"PASS browser {options.phase}: {run.checks} checks, {len(run.shots)} screenshots, "
        "no page or console errors"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
