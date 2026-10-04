"""Exercise the backend-free provider query used by the Phase 6 lock check."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_new_provider_flow import literal_check, phase_six_steps

REFERENCES = Path(__file__).resolve().parents[1] / ".ai-rulez/skills/infra-copilot/references"
CHECK = REFERENCES / "checks/provider-requirements.sh"
LOCK = ('provider "registry.terraform.io/hashicorp/google" {\n'
        '  version = "6.0.0"\n  hashes = [\n    "h1:fixture",\n  ]\n}\n')
CONFIG = '''terraform {
  cloud {
    organization = "acme"
    workspaces { name = "gcp" }
  }
  required_providers {
    google = { source = "hashicorp/google" }
  }
}
'''


@unittest.skipUnless(os.name == "posix", "checks use POSIX shell")
class ProviderRequirementsTests(unittest.TestCase):
    def run_check(self, files: dict[str, str], *, status: int = 0,
                  providers: str = "registry.terraform.io/hashicorp/google",
                  lock: str | None = LOCK) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="provider check ") as directory:
            root = Path(directory)
            leaf = root / "terraform/gcp"
            leaf.mkdir(parents=True)
            for name, content in files.items():
                (leaf / name).write_text(content)
            if lock is not None:
                (leaf / ".terraform.lock.hcl").write_text(lock)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            executable = bin_dir / "terraform"
            executable.write_text('''#!/bin/sh
[ "$#" = 3 ] && [ "$2" = providers ] && [ "$3" = -no-color ] || exit 9
scratch=${1#-chdir=}
[ "$scratch" != "$ORIGINAL_LEAF" ] || exit 9
[ "$TF_DATA_DIR" = "$scratch/.terraform" ] || exit 9
[ "$TF_WORKSPACE" = default ] || exit 9
[ -z "$TF_CLI_ARGS$TF_CLI_ARGS_providers" ] || exit 9
[ ! -e "$scratch/.terraform.lock.hcl" ] || exit 9
cat "$scratch"/*.tf "$scratch"/*.tf.json 2>/dev/null >"$CAPTURE"
[ "$QUERY_STATUS" = 0 ] || exit "$QUERY_STATUS"
echo 'Providers required by configuration:'
printf '%s\\n' "$QUERY_PROVIDERS" | while IFS= read -r address; do
  [ -z "$address" ] || printf 'provider[%s]\\n' "$address"
done
''')
            executable.chmod(0o755)
            before = {p.relative_to(leaf): p.read_bytes() for p in leaf.rglob("*") if p.is_file()}
            env = os.environ | {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "ORIGINAL_LEAF": str(leaf), "CAPTURE": str(root / "capture"),
                "QUERY_STATUS": str(status), "QUERY_PROVIDERS": providers,
                "NEW_PROVIDER": "gcp", "INFRA_COPILOT_REFERENCES": str(REFERENCES),
                "TF_DATA_DIR": str(leaf / ".terraform"), "TF_WORKSPACE": "production",
                "TF_CLI_ARGS": "-invalid", "TF_CLI_ARGS_providers": "-invalid",
            }
            result = subprocess.run(
                ["sh", "-c", literal_check(phase_six_steps()["new-provider-lock"])],
                cwd=root, env=env, text=True, capture_output=True,
            )
            after = {p.relative_to(leaf): p.read_bytes() for p in leaf.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertFalse((leaf / ".terraform").exists())
            capture = root / "capture"
            self.copied_config = capture.read_text() if capture.exists() else ""
            return result

    def test_cloud_leaf_passes_without_initialization_and_keeps_requirements(self) -> None:
        result = self.run_check({"versions.tf": CONFIG})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("organization", self.copied_config)
        self.assertNotIn("workspaces", self.copied_config)
        self.assertIn('source = "hashicorp/google"', self.copied_config)

    def test_json_and_override_backends_are_removed(self) -> None:
        result = self.run_check({
            "versions.tf": CONFIG,
            "override.tf.json": '{"terraform":{"backend":{"s3":{"bucket":"secret"}}}}',
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("bucket", self.copied_config)
        self.assertNotIn("organization", self.copied_config)

    def test_comments_strings_and_heredocs_do_not_change_structure(self) -> None:
        config = CONFIG.replace("  cloud {", '  /* } fake terraform { */ cloud\n  {')
        config += '''locals {
  text = "cloud { backend \\\"s3\\\" { } }"
  document = <<-EOT
    terraform { cloud { } }
    EOT
}
'''
        result = self.run_check({"main.tf": config})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('terraform { cloud { } }', self.copied_config)
        self.assertNotIn("organization", self.copied_config)

    def test_missing_selection_version_or_hash_is_incomplete(self) -> None:
        for lock in (None, "", LOCK.replace('version = "6.0.0"', ""),
                     LOCK.replace('"h1:fixture",', "")):
            with self.subTest(lock=lock):
                self.assertEqual(self.run_check({"main.tf": CONFIG}, lock=lock).returncode, 1)

    def test_every_external_provider_is_required(self) -> None:
        result = self.run_check({"main.tf": CONFIG}, providers=(
            "registry.terraform.io/hashicorp/google\nexample.com/team/custom"))
        self.assertEqual(result.returncode, 1)

    def test_builtin_or_provider_free_configuration_needs_no_lock(self) -> None:
        for providers in ("terraform.io/builtin/terraform", ""):
            with self.subTest(providers=providers):
                result = self.run_check({"main.tf": CONFIG}, providers=providers, lock=None)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_query_failure_and_unreadable_configuration_are_unknown(self) -> None:
        for files, status in (({"main.tf": CONFIG}, 1), ({}, 0),
                              ({"main.tf.json": "{broken"}, 0),
                              ({"main.tf": CONFIG + "/*"}, 0)):
            with self.subTest(files=files, status=status):
                result = self.run_check(files, status=status)
                self.assertEqual(result.returncode, 2, result.stderr)


REAL_TERRAFORM = os.environ.get("INFRA_COPILOT_TEST_TERRAFORM")


@unittest.skipUnless(REAL_TERRAFORM, "set INFRA_COPILOT_TEST_TERRAFORM for CLI integration")
class RealTerraformProviderRequirementsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = os.environ | {
            "PATH": f"{Path(REAL_TERRAFORM).parent}{os.pathsep}{os.environ['PATH']}"
        }

    def test_real_cloud_and_json_leaves_without_init(self) -> None:
        configurations = [
            {"main.tf": CONFIG},
            {"main.tf": CONFIG.replace("\n", "\r\n")},
            {"main.tf.json": '''{"terraform":{"cloud":{"organization":"fake",
              "workspaces":{"name":"fake"}},"required_providers":{
              "google":{"source":"hashicorp/google"}}}}'''},
            {"main.tf": CONFIG, "main_override.tf": 'terraform {\n backend "s3" {\n bucket = "fake"\n }\n}\n'},
            {"main.tf": 'resource "google_storage_bucket" "test" { name = "test" }\n'},
            {"main.tf": 'data "terraform_remote_state" "test" { backend = "local" }\n'},
        ]
        for files in configurations:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, content in files.items():
                    (root / name).write_text(content)
                before = {p.name: p.read_bytes() for p in root.iterdir()}
                result = subprocess.run(["sh", str(CHECK), directory],
                                        capture_output=True, text=True, env=self.env)
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = ("terraform.io/builtin/terraform" if "data " in str(files)
                            else "registry.terraform.io/hashicorp/google")
                self.assertEqual(result.stdout.strip(), expected)
                self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_installed_local_module_provider_is_included(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            leaf = root / "gcp"
            leaf.mkdir()
            (leaf / "main.tf").write_text(CONFIG + 'module "child" { source = "../child" }\n')
            child = root / "child"
            child.mkdir()
            (child / "main.tf").write_text('resource "random_pet" "test" {}\n')
            modules = leaf / ".terraform/modules"
            modules.mkdir(parents=True)
            (modules / "modules.json").write_text(json.dumps({"Modules": [
                {"Key": "", "Source": "", "Dir": "."},
                {"Key": "child", "Source": "../child", "Dir": "../child"},
            ]}))
            result = subprocess.run(["sh", str(CHECK), str(leaf)], capture_output=True, text=True, env=self.env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "registry.terraform.io/hashicorp/google", "registry.terraform.io/hashicorp/random"])

    def test_uninstalled_module_and_invalid_hcl_are_unknown(self) -> None:
        for content in (CONFIG + 'module "child" { source = "./missing" }\n',
                        'resource "google_storage_bucket" { invalid'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                (Path(directory) / "main.tf").write_text(content)
                result = subprocess.run(["sh", str(CHECK), directory], capture_output=True, text=True, env=self.env)
                self.assertEqual(result.returncode, 2, result.stderr)
