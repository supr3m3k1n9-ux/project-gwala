"""Tests for the read-only Linux host security verifier."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy.linux.write_host_security_health import (
    compose_security_fallback,
    credential_leak_check,
    docker_inspect_check,
    listening_ports_check,
    root_wrapper_permissions_check,
    secret_file_permissions_check,
    ssh_hardening_check,
    ufw_check,
)


SAFE_SSHD = """
permitrootlogin no
passwordauthentication no
pubkeyauthentication yes
"""


class HostSecurityHealthTests(unittest.TestCase):
    def test_repository_compose_declares_no_new_privileges(self) -> None:
        compose = Path(__file__).resolve().parents[1] / "compose.yaml"
        text = compose.read_text(encoding="utf-8")

        self.assertIn("security_opt:", text)
        self.assertIn("no-new-privileges:true", text.replace(" ", ""))
        self.assertIn('user: "1000:1000"', text)
        self.assertIn('"127.0.0.1:8765:8765"', text)

    def test_safe_ssh_config_is_green(self) -> None:
        check = ssh_hardening_check(SAFE_SSHD)
        self.assertEqual(check["status"], "GREEN")

    def test_root_or_password_ssh_enabled_is_red(self) -> None:
        check = ssh_hardening_check(
            """
permitrootlogin yes
passwordauthentication yes
pubkeyauthentication yes
"""
        )
        self.assertEqual(check["status"], "RED")
        self.assertIn("permitrootlogin=yes", check["reason"])
        self.assertIn("passwordauthentication=yes", check["reason"])

    def test_ufw_disabled_is_red(self) -> None:
        check = ufw_check("Status: inactive\n")
        self.assertEqual(check["status"], "RED")

    def test_dashboard_public_listener_is_red(self) -> None:
        text = """
Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
tcp LISTEN 0 4096 0.0.0.0:5000 0.0.0.0:* users:(("python",pid=12,fd=3))
"""
        check, summary = listening_ports_check(text)
        self.assertEqual(check["status"], "RED")
        self.assertTrue(summary["dashboard_public"])

    def test_docker_tcp_exposed_is_red(self) -> None:
        text = """
Netid State Recv-Q Send-Q Local Address:Port Peer Address:Port Process
tcp LISTEN 0 4096 0.0.0.0:2375 0.0.0.0:* users:(("dockerd",pid=12,fd=3))
"""
        check, summary = listening_ports_check(text)
        self.assertEqual(check["status"], "RED")
        self.assertTrue(summary["docker_tcp_exposed"])

    def test_docker_socket_mounted_into_container_is_red(self) -> None:
        check = docker_inspect_check(
            [
                {
                    "Name": "/project-gwala-app",
                    "Config": {"User": "1000:1000"},
                    "HostConfig": {
                        "Privileged": False,
                        "NetworkMode": "bridge",
                        "PidMode": "",
                        "IpcMode": "",
                        "Devices": [],
                        "SecurityOpt": ["no-new-privileges:true"],
                        "Binds": ["/var/run/docker.sock:/var/run/docker.sock"],
                    },
                    "Mounts": [],
                }
            ]
        )
        self.assertEqual(check["status"], "RED")
        self.assertIn("Docker socket mounted", check["reason"])

    def test_valid_docker_inspect_json_is_parsed_correctly(self) -> None:
        with patch(
            "deploy.linux.write_host_security_health.run_command_full",
            return_value=(0, json.dumps([self.good_container()])),
        ):
            check = docker_inspect_check(
                inspect_payload=None,
                runner=lambda command, timeout: (0, "container123") if command[:2] == ["docker", "ps"] else (1, ""),
            )

        self.assertEqual(check["status"], "GREEN")

    def test_malformed_docker_inspect_output_is_watch(self) -> None:
        with patch("deploy.linux.write_host_security_health.run_command_full", return_value=(0, "not-json")):
            check = docker_inspect_check(
                inspect_payload=None,
                runner=lambda command, timeout: (0, "container123") if command[:2] == ["docker", "ps"] else (1, ""),
            )

        self.assertEqual(check["status"], "WATCH")
        self.assertIn("invalid JSON", check["reason"])

    def test_no_running_oneshot_container_is_not_red(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            compose = root / "compose.yaml"
            compose.write_text("services: {}\n", encoding="utf-8")
            compose_payload = {
                "services": {
                    "app": {
                        "user": "1000:1000",
                        "security_opt": ["no-new-privileges:true"],
                        "cap_drop": ["ALL"],
                    }
                }
            }
            with patch(
                "deploy.linux.write_host_security_health.run_command_full",
                return_value=(0, json.dumps(compose_payload)),
            ):
                check = docker_inspect_check(
                    inspect_payload=None,
                    runner=lambda command, timeout: (0, "") if command[:2] == ["docker", "ps"] else (1, ""),
                    compose_file=compose,
                )

        self.assertEqual(check["status"], "WATCH")
        self.assertNotEqual(check["status"], "RED")
        self.assertIn("No running Gwala container", check["reason"])

    def test_privileged_container_is_red(self) -> None:
        check = docker_inspect_check(
            [
                {
                    "Name": "/project-gwala-app",
                    "Config": {"User": "1000:1000"},
                    "HostConfig": {
                        "Privileged": True,
                        "NetworkMode": "bridge",
                        "PidMode": "",
                        "IpcMode": "",
                        "Devices": [],
                        "SecurityOpt": ["no-new-privileges:true"],
                    },
                    "Mounts": [],
                }
            ]
        )
        self.assertEqual(check["status"], "RED")
        self.assertIn("privileged=true", check["reason"])

    def test_host_network_container_is_red(self) -> None:
        container = self.good_container()
        container["HostConfig"]["NetworkMode"] = "host"
        check = docker_inspect_check([container])
        self.assertEqual(check["status"], "RED")
        self.assertIn("host network", check["reason"])

    def test_uid_1000_non_root_container_is_green(self) -> None:
        check = docker_inspect_check([self.good_container()])
        self.assertEqual(check["status"], "GREEN")

    def test_declared_no_new_privileges_is_green(self) -> None:
        container = self.good_container()

        check = docker_inspect_check([container])

        self.assertEqual(check["status"], "GREEN")
        self.assertNotIn("no-new-privileges", check["reason"])

    def test_absent_no_new_privileges_remains_watch(self) -> None:
        container = self.good_container()
        container["HostConfig"]["SecurityOpt"] = []

        check = docker_inspect_check([container])

        self.assertEqual(check["status"], "WATCH")
        self.assertIn("no-new-privileges not declared", check["reason"])

    def test_compose_declared_no_new_privileges_removes_compose_warning(self) -> None:
        with TemporaryDirectory() as raw:
            compose = Path(raw) / "compose.yaml"
            compose.write_text("services:\n  gwala:\n    image: project-gwala:latest\n", encoding="utf-8")
            compose_payload = {
                "services": {
                    "gwala": {
                        "image": "project-gwala:latest",
                        "user": "1000:1000",
                        "security_opt": ["no-new-privileges:true"],
                        "volumes": [],
                    }
                }
            }
            with patch(
                "deploy.linux.write_host_security_health.run_command_full",
                return_value=(0, json.dumps(compose_payload)),
            ):
                check = compose_security_fallback(compose)

        self.assertEqual(check["status"], "WATCH")
        self.assertIn("Runtime-only fields remain unverified", check["reason"])
        self.assertNotIn("no-new-privileges not declared", check["reason"])

    @staticmethod
    def good_container() -> dict[str, object]:
        return {
            "Name": "/project-gwala-app",
            "Config": {"User": "1000:1000"},
            "HostConfig": {
                "Privileged": False,
                "NetworkMode": "bridge",
                "PidMode": "",
                "IpcMode": "",
                "Devices": [],
                "SecurityOpt": ["no-new-privileges:true"],
                "CapAdd": [],
                "CapDrop": ["ALL"],
                "Binds": [],
            },
            "Mounts": [],
        }

    def test_secret_env_file_0600_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            config = root / "config"
            token_dir = config / "webull_tokens"
            token_dir.mkdir(parents=True)
            env_file = config / "gwala.env"
            token = token_dir / "token.json"
            env_file.write_text("WEBULL_APP_KEY=redacted\n", encoding="utf-8")
            token.write_text("redacted\n", encoding="utf-8")
            os.chmod(config, 0o700)
            os.chmod(token_dir, 0o700)
            os.chmod(env_file, 0o600)
            os.chmod(token, 0o600)

            check = secret_file_permissions_check(root)

        self.assertEqual(check["status"], "GREEN")

    def test_secret_env_file_0644_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            config = root / "config"
            token_dir = config / "webull_tokens"
            token_dir.mkdir(parents=True)
            env_file = config / "gwala.env"
            token = token_dir / "token.json"
            env_file.write_text("WEBULL_APP_KEY=redacted\n", encoding="utf-8")
            token.write_text("redacted\n", encoding="utf-8")
            os.chmod(config, 0o700)
            os.chmod(token_dir, 0o700)
            os.chmod(env_file, 0o644)
            os.chmod(token, 0o600)

            check = secret_file_permissions_check(root)

        self.assertEqual(check["status"], "RED")
        self.assertIn("gwala.env permissions", check["reason"])

    def test_webull_token_file_0600_is_green(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            config = root / "config"
            token_dir = config / "webull_tokens"
            token_dir.mkdir(parents=True)
            (config / "gwala.env").write_text("x\n", encoding="utf-8")
            token = token_dir / "token.json"
            token.write_text("x\n", encoding="utf-8")
            for path in [config, token_dir]:
                os.chmod(path, 0o700)
            for path in [config / "gwala.env", token]:
                os.chmod(path, 0o600)

            check = secret_file_permissions_check(root)

        self.assertEqual(check["status"], "GREEN")

    def test_root_run_wrapper_writable_by_ordinary_user_is_red(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            systemd_dir = root / "systemd"
            systemd_dir.mkdir()
            wrapper = root / "deploy_latest.sh"
            wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
            os.chmod(wrapper, 0o775)

            check = root_wrapper_permissions_check(root, systemd_dir=systemd_dir)

        self.assertEqual(check["status"], "RED")
        self.assertIn("writable by group/other", check["reason"])

    def test_credential_match_reports_file_and_key_but_not_secret_value(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            logs = root / "logs"
            logs.mkdir()
            secret = "real_secret_value_123456"
            leaked = logs / "app.log"
            leaked.write_text(f"token={secret}\n", encoding="utf-8")

            with patch("deploy.linux.write_host_security_health.tracked_repository_files", return_value=[]):
                check = credential_leak_check(root, env={"WEBULL_APP_SECRET": secret})

        text = json.dumps(check)
        self.assertEqual(check["status"], "RED")
        self.assertIn("WEBULL_APP_SECRET", text)
        self.assertIn(str(leaked), text)
        self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
