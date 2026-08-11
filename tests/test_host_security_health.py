"""Tests for the read-only Linux host security verifier."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from deploy.linux.write_host_security_health import (
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
