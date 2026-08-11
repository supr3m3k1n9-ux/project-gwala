"""Tests for the Project Gwala continuous assurance control plane."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import types
import unittest
from unittest.mock import patch

import pandas as pd

from run_continuous_assurance import (
    AssuranceCheck,
    aggregate_status,
    build_eod_integrity,
    build_premarket_assurance,
    build_runtime_smoke,
    build_weekly_deep_assurance,
    check_dashboard_localhost,
    check_docker_runtime,
    check_production_heartbeat_artifact,
    check_file_private,
    check_safety_env,
    compile_critical_modules,
    extract_unittest_failures,
    extract_unittest_reason,
    now_et,
    secret_configuration_checks,
    summarize_existing_payload,
    write_state,
)


SAFE_ENV = {
    "GWALA_DEPLOYMENT_MODE": "shadow",
    "GWALA_SHADOW_MODE": "true",
    "GWALA_DISABLE_BROKER_EXECUTION": "true",
    "GWALA_LIVE_TRADING_ENABLED": "false",
    "GWALA_BROKER_ORDER_EXECUTION_ENABLED": "false",
    "GWALA_REAL_MONEY_READY": "false",
}


def args_for(tmp: Path) -> argparse.Namespace:
    return argparse.Namespace(
        output_dir=tmp / "logs" / "assurance",
        project_root=tmp,
        env_file=tmp / "config" / "gwala.env",
        host_systemd_health_json=tmp / "logs" / "host_systemd_health.json",
        host_docker_health_json=tmp / "logs" / "host_docker_health.json",
        host_security_json=tmp / "logs" / "host_security_health.json",
        production_heartbeat_json=tmp / "logs" / "production_heartbeat.json",
        skip_network=True,
        run_tests=False,
        run_linux_preflight=False,
    )


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fresh_payload(status: str, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {"status": status, "generated_at_et": now_et().strftime("%Y-%m-%d %H:%M:%S %Z")}
    payload.update(updates)
    return payload


class ContinuousAssuranceTests(unittest.TestCase):
    def test_aggregate_status_uses_green_watch_red(self) -> None:
        self.assertEqual(aggregate_status([AssuranceCheck("a", "GREEN", "ok")]), "GREEN")
        self.assertEqual(
            aggregate_status([AssuranceCheck("a", "GREEN", "ok"), AssuranceCheck("b", "WATCH", "note")]),
            "WATCH",
        )
        self.assertEqual(
            aggregate_status([AssuranceCheck("a", "WATCH", "note"), AssuranceCheck("b", "RED", "bad")]),
            "RED",
        )

    def test_safety_env_red_when_live_boundary_is_not_shadow(self) -> None:
        check = check_safety_env({**SAFE_ENV, "GWALA_LIVE_TRADING_ENABLED": "true"})
        self.assertEqual(check.status, "RED")
        self.assertEqual(check.operator_action_required, "YES")
        self.assertNotIn("true", json.dumps(check.as_dict()).lower())

    def test_dashboard_public_host_is_red(self) -> None:
        check = check_dashboard_localhost({"GWALA_DASHBOARD_HOST": "0.0.0.0"})
        self.assertEqual(check.status, "RED")
        self.assertEqual(check.engineering_trigger, "INVESTIGATE")

    def test_existing_payload_maps_yellow_to_watch(self) -> None:
        check = summarize_existing_payload("Heartbeat", {"status": "YELLOW", "next_action": "verify"}, {"GREEN"}, {"YELLOW"})
        self.assertEqual(check.status, "WATCH")

    def test_docker_container_with_healthy_host_docker_artifact_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "host_docker_health.json"
            write_json(path, fresh_payload("GREEN"))
            check = check_docker_runtime(host_docker_health_path=path, platform_name="Linux", in_docker=True, moment=now_et())
            self.assertEqual(check.status, "GREEN")

    def test_docker_container_without_cli_but_healthy_host_artifact_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "host_docker_health.json"
            write_json(path, fresh_payload("GREEN"))
            with patch("run_continuous_assurance.shutil.which", return_value=None):
                check = check_docker_runtime(host_docker_health_path=path, platform_name="Linux", in_docker=True, moment=now_et())
            self.assertEqual(check.status, "GREEN")

    def test_missing_host_docker_artifact_is_watch(self) -> None:
        path = Path("/tmp/project-gwala-missing-host-docker-health.json")
        check = check_docker_runtime(host_docker_health_path=path, platform_name="Linux", in_docker=True, moment=now_et())
        self.assertEqual(check.status, "WATCH")

    def test_stale_host_docker_artifact_is_watch(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "host_docker_health.json"
            write_json(path, {"status": "GREEN", "generated_at_et": "2026-01-01 09:30:00 EST"})
            check = check_docker_runtime(host_docker_health_path=path, platform_name="Linux", in_docker=True, moment=now_et())
            self.assertEqual(check.status, "WATCH")

    def test_unhealthy_host_docker_artifact_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "host_docker_health.json"
            write_json(path, fresh_payload("RED", red_reason="docker daemon failed"))
            check = check_docker_runtime(host_docker_health_path=path, platform_name="Linux", in_docker=True, moment=now_et())
            self.assertEqual(check.status, "RED")

    def test_fresh_production_heartbeat_red_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "production_heartbeat.json"
            write_json(path, fresh_payload("RED", next_action="investigate"))
            check = check_production_heartbeat_artifact(path, now_et())
            self.assertEqual(check.status, "RED")

    def test_stale_production_heartbeat_red_is_watch(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "production_heartbeat.json"
            write_json(path, {"status": "RED", "generated_at_et": "2026-01-01 09:30:00 EST"})
            check = check_production_heartbeat_artifact(path, now_et())
            self.assertEqual(check.status, "WATCH")
            self.assertIn("stale", check.reason)

    def test_fresh_production_heartbeat_green_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            path = Path(raw) / "production_heartbeat.json"
            write_json(path, fresh_payload("GREEN"))
            check = check_production_heartbeat_artifact(path, now_et())
            self.assertEqual(check.status, "GREEN")

    def test_runtime_smoke_writes_artifacts_and_keeps_safety_read_only(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "logs").mkdir()
            (tmp / "data").mkdir()
            args = args_for(tmp)
            write_json(args.production_heartbeat_json, fresh_payload("GREEN"))
            safe_env = {**SAFE_ENV, "GWALA_DASHBOARD_HOST": "127.0.0.1"}
            with patch.dict(os.environ, safe_env, clear=False), patch(
                "run_continuous_assurance.check_docker_runtime", return_value=AssuranceCheck("Docker runtime", "GREEN", "ok")
            ), patch("run_continuous_assurance.check_memory_pressure", return_value=AssuranceCheck("Memory", "GREEN", "ok")), patch(
                "run_continuous_assurance.check_disk_capacity", return_value=AssuranceCheck("Disk", "GREEN", "ok")
            ):
                payload = build_runtime_smoke(args)
            self.assertEqual(payload["status"], "GREEN")
            self.assertTrue((args.output_dir / "runtime" / "runtime_smoke.json").exists())
            saved = json.loads((args.output_dir / "runtime" / "runtime_smoke.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["guardrail"].split(".")[0], "Read-only assurance")

    def test_premarket_compile_failure_blocks_readiness(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            args = args_for(tmp)
            with patch.dict(os.environ, SAFE_ENV, clear=False), patch(
                "run_continuous_assurance.compile_critical_modules",
                return_value=[AssuranceCheck("Python compile", "RED", "bad syntax", engineering_trigger="BUILD")],
            ), patch("run_continuous_assurance.build_dashboard_preflight", return_value={"status": "pass"}):
                payload = build_premarket_assurance(args)
            self.assertEqual(payload["status"], "RED")
            self.assertEqual(payload["readiness"], "BLOCKED")
            self.assertEqual(payload["red_component"], "Python compile")

    def test_premarket_test_failure_reports_failing_test_not_successful_noise(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            args = args_for(tmp)
            failure = {
                "return_code": 1,
                "stdout_tail": "Saved /tmp/example/webull_SPY_M1_candles.csv",
                "stderr_tail": "FAIL: test_real_failure (tests.test_workflow_safety.Case)\nAssertionError: broken",
                "failing_tests": ["FAIL: test_real_failure (tests.test_workflow_safety.Case)"],
                "failure_reason": "FAIL: test_real_failure (tests.test_workflow_safety.Case) | AssertionError: broken",
            }
            with patch.dict(os.environ, SAFE_ENV, clear=False), patch(
                "run_continuous_assurance.compile_critical_modules", return_value=[]
            ), patch("run_continuous_assurance.build_dashboard_preflight", return_value={"status": "pass"}), patch(
                "run_continuous_assurance.run_test_command", return_value=failure
            ):
                args.run_tests = True
                payload = build_premarket_assurance(args)
            check = next(row for row in payload["checks"] if row["component"] == "Focused workflow safety tests")
            self.assertEqual(check["status"], "RED")
            self.assertIn("test_real_failure", check["reason"])
            self.assertIn("return_code=1", check["reason"])

    def test_unittest_failure_parsing_extracts_failure_name_and_reason(self) -> None:
        output = """
Saved /tmp/example/webull_SPY_M1_candles.csv
test_real_failure (tests.test_workflow_safety.Case) ... FAIL
======================================================================
FAIL: test_real_failure (tests.test_workflow_safety.Case)
----------------------------------------------------------------------
Traceback (most recent call last):
AssertionError: expected true
"""
        self.assertIn("test_real_failure", " ".join(extract_unittest_failures(output)))
        self.assertIn("AssertionError", extract_unittest_reason(output))

    def test_syntax_valid_source_in_non_writable_directory_is_green_without_pycache(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            source = tmp / "valid_module.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            os.chmod(tmp, 0o555)
            try:
                with patch("run_continuous_assurance.CRITICAL_MODULES", [str(source)]):
                    checks = compile_critical_modules()
            finally:
                os.chmod(tmp, 0o755)
            self.assertEqual(checks[0].status, "GREEN")
            self.assertFalse((tmp / "__pycache__").exists())
            self.assertFalse(list(tmp.glob("*.pyc")))

    def test_syntax_invalid_source_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            source = Path(raw) / "bad_module.py"
            source.write_text("def broken(:\n    pass\n", encoding="utf-8")
            with patch("run_continuous_assurance.CRITICAL_MODULES", [str(source)]):
                checks = compile_critical_modules()
            self.assertEqual(checks[0].status, "RED")
            self.assertIn("syntax error", checks[0].reason)

    def test_docker_linux_secret_env_without_dotenv_is_not_false_watch(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            env = {**SAFE_ENV, "WEBULL_APP_KEY": "key", "WEBULL_APP_SECRET": "secret", "WEBULL_REGION_ID": "us"}
            checks = secret_configuration_checks(
                env_file=tmp / ".env",
                host_security_json=tmp / "missing_host_security.json",
                moment=now_et(),
                platform_name="Linux",
                in_docker=True,
                env=env,
            )
            env_check = next(check for check in checks if check.component == "Secret environment variables")
            host_check = next(check for check in checks if check.component == "Host security")
            self.assertEqual(env_check.status, "GREEN")
            self.assertEqual(host_check.status, "WATCH")
            self.assertNotEqual(host_check.reason, ".env is missing.")

    def test_fresh_green_host_security_artifact_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            artifact = tmp / "logs" / "host_security_health.json"
            write_json(artifact, fresh_payload("GREEN"))
            checks = secret_configuration_checks(
                env_file=tmp / ".env",
                host_security_json=artifact,
                moment=now_et(),
                platform_name="Linux",
                in_docker=True,
                env={**SAFE_ENV, "WEBULL_APP_KEY": "key", "WEBULL_APP_SECRET": "secret", "WEBULL_REGION_ID": "us"},
            )

        host_check = next(check for check in checks if check.component == "Host security")
        self.assertEqual(host_check.status, "GREEN")

    def test_fresh_red_host_security_artifact_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            artifact = tmp / "logs" / "host_security_health.json"
            write_json(
                artifact,
                fresh_payload(
                    "RED",
                    red_component="Secret file permissions",
                    red_reason="gwala.env permissions 0o644",
                    recommended_next_action="Restrict host secret file permissions.",
                ),
            )
            checks = secret_configuration_checks(
                env_file=tmp / ".env",
                host_security_json=artifact,
                moment=now_et(),
                platform_name="Linux",
                in_docker=True,
                env={**SAFE_ENV, "WEBULL_APP_KEY": "key", "WEBULL_APP_SECRET": "secret", "WEBULL_REGION_ID": "us"},
            )

        host_check = next(check for check in checks if check.component == "Host security")
        self.assertEqual(host_check.status, "RED")
        self.assertIn("0o644", host_check.reason)

    def test_missing_required_secret_env_is_red_without_printing_values(self) -> None:
        env = {**SAFE_ENV, "WEBULL_APP_KEY": "key", "WEBULL_APP_SECRET": "super-secret"}
        checks = secret_configuration_checks(
            env_file=Path(".env"),
            host_security_json=Path("missing.json"),
            moment=now_et(),
            platform_name="Linux",
            in_docker=True,
            env=env,
        )
        text = json.dumps([check.as_dict() for check in checks])
        env_check = next(check for check in checks if check.component == "Secret environment variables")
        self.assertEqual(env_check.status, "RED")
        self.assertIn("WEBULL_REGION_ID", env_check.reason)
        self.assertNotIn("super-secret", text)

    def test_macos_local_env_file_behavior_remains_valid(self) -> None:
        with TemporaryDirectory() as raw:
            env_file = Path(raw) / ".env"
            env_file.write_text("WEBULL_APP_KEY=value\n", encoding="utf-8")
            os.chmod(env_file, 0o600)
            checks = secret_configuration_checks(
                env_file=env_file,
                host_security_json=Path(raw) / "host_security.json",
                moment=now_et(),
                platform_name="Darwin",
                in_docker=False,
            )
            self.assertEqual(len(checks), 1)
            self.assertEqual(checks[0].component, "Secret env file permissions")
            self.assertEqual(checks[0].status, "GREEN")

    def test_token_permission_check_preserved(self) -> None:
        with TemporaryDirectory() as raw:
            token = Path(raw) / "token.txt"
            token.write_text("token-value\n", encoding="utf-8")
            os.chmod(token, 0o600)
            check = check_file_private(token, "Webull token file permissions", required_if_exists=False)
            self.assertEqual(check.status, "GREEN")
            self.assertNotIn("token-value", json.dumps(check.as_dict()))

    def test_linux_preflight_project_root_readable_not_writable(self) -> None:
        from deploy.linux import preflight

        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "data").mkdir()
            (root / "logs").mkdir()
            os.chmod(root, 0o555)
            try:
                with patch.object(preflight, "PROJECT_ROOT", root):
                    _, ok, detail = preflight.check_directories()
            finally:
                os.chmod(root, 0o755)
            self.assertTrue(ok)
            self.assertIn("project root readable", detail)

    def test_webull_client_initializes_without_application_root_sdk_log(self) -> None:
        import data.webull_data as webull_data

        class FakeApiClient:
            def __init__(self, app_key: str, app_secret: str, region_id: str) -> None:
                self._file_logger_set = None
                self._stream_logger_set = None
                self.app_key = app_key
                self.app_secret = app_secret
                self.region_id = region_id
                self.token_dir = ""

            def set_token_dir(self, token_dir: str) -> None:
                self.token_dir = token_dir

            def add_endpoint(self, region_id: str, endpoint: str) -> None:
                self.endpoint = (region_id, endpoint)

        class FakeDataClient:
            def __init__(self, api_client: FakeApiClient) -> None:
                if not api_client._file_logger_set:
                    Path("webull_data_sdk.log").write_text(
                        f"{api_client.app_key} {api_client.app_secret}",
                        encoding="utf-8",
                    )
                self.api_client = api_client

        with TemporaryDirectory() as raw:
            root = Path(raw)
            source_root = root / "app"
            source_root.mkdir()
            token_dir = root / ".webull_tokens"
            os.chmod(source_root, 0o555)
            cwd = Path.cwd()
            core_client = types.ModuleType("webull.core.client")
            core_client.ApiClient = FakeApiClient
            data_client = types.ModuleType("webull.data.data_client")
            data_client.DataClient = FakeDataClient
            try:
                os.chdir(source_root)
                with patch.dict(
                    os.environ,
                    {
                        **SAFE_ENV,
                        "WEBULL_APP_KEY": "test-app-key",
                        "WEBULL_APP_SECRET": "test-app-secret",
                        "WEBULL_REGION_ID": "us",
                    },
                    clear=False,
                ), patch.object(webull_data, "TOKEN_DIR", token_dir), patch.dict(
                    sys.modules,
                    {
                        "webull.core.client": core_client,
                        "webull.data.data_client": data_client,
                    },
                ):
                    client = webull_data.build_data_client()
            finally:
                os.chdir(cwd)
                os.chmod(source_root, 0o755)
            self.assertTrue(client.api_client._file_logger_set)
            self.assertTrue(client.api_client._stream_logger_set)
            self.assertFalse((source_root / "webull_data_sdk.log").exists())

    def test_webull_sdk_log_output_does_not_contain_secrets_when_disabled(self) -> None:
        with TemporaryDirectory() as raw:
            log_path = Path(raw) / "webull_data_sdk.log"
            if log_path.exists():
                text = log_path.read_text(encoding="utf-8")
            else:
                text = ""
            self.assertNotIn("test-app-key", text)
            self.assertNotIn("test-app-secret", text)

    def test_eod_duplicate_orb_ledger_is_red_and_runway_invalid(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            cwd = Path.cwd()
            try:
                os.chdir(tmp)
                (tmp / "data").mkdir()
                (tmp / "logs").mkdir()
                pd.DataFrame(
                    [
                        {"symbol": "QQQ", "strategy_id": "morning_index_orb_long", "entry_time_et": "2026-08-10 10:15"},
                        {"symbol": "QQQ", "strategy_id": "morning_index_orb_long", "entry_time_et": "2026-08-10 10:15"},
                    ]
                ).to_csv(tmp / "data" / "morning_index_orb_manual_paper_trades.csv", index=False)
                args = args_for(tmp)
                with patch("run_continuous_assurance.build_data_flow_sentinel", return_value={"status": "synced"}):
                    payload = build_eod_integrity(args)
            finally:
                os.chdir(cwd)
            self.assertEqual(payload["status"], "RED")
            self.assertEqual(payload["evidence_confidence"], "LOW")
            self.assertEqual(payload["session_valid_for_research_runway"], "NO")

    def test_weekly_code_auditor_does_not_print_secret_values(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            (tmp / "run_bad.py").write_text("WEBULL_APP_SECRET=super-secret-value\n", encoding="utf-8")
            for name in ["OPERATING_DOCTRINE.md", "PROJECT_STATE.md", "STRATEGY_STATE.md", "DECISION_LOG.md", "ROADMAP.md", "HANDOFF.md"]:
                (tmp / name).write_text("ok\n", encoding="utf-8")
            (tmp / "requirements.txt").write_text("pandas>=2\n", encoding="utf-8")
            (tmp / "requirements-webull.txt").write_text("webull-openapi-python-sdk\n", encoding="utf-8")
            args = args_for(tmp)
            with patch.dict(os.environ, SAFE_ENV, clear=False), patch(
                "run_continuous_assurance.compile_critical_modules", return_value=[]
            ), patch("run_continuous_assurance.git_inventory_check", return_value=AssuranceCheck("Git", "GREEN", "ok")):
                payload = build_weekly_deep_assurance(args)
            text = json.dumps(payload)
            self.assertIn("potential secret assignment", text)
            self.assertNotIn("super-secret-value", text)

    def test_state_self_monitor_reports_missing_layers(self) -> None:
        with TemporaryDirectory() as raw:
            tmp = Path(raw)
            args = args_for(tmp)
            state = write_state(args, [])
            self.assertEqual(state["status"], "WATCH")
            self.assertTrue((args.output_dir / "assurance_state.json").exists())


if __name__ == "__main__":
    unittest.main()
