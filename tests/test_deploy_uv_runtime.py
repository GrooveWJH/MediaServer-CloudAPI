import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


class DeployUvRuntimeTest(unittest.TestCase):
    def test_service_templates_use_project_venv_python(self):
        expected = "/opt/mediaserver/MediaServer-CloudAPI/.venv/bin/python"
        self.assertIn(expected, _read("deploy/media-server.service"))
        self.assertIn(expected, _read("deploy/media-web.service"))

    def test_setup_script_bootstraps_uv_and_syncs_dependencies(self):
        setup = _read("deploy/setup.sh")
        self.assertIn("command -v python3", setup)
        self.assertIn("command -v uv", setup)
        self.assertIn("astral.sh/uv/install.sh", setup)
        self.assertIn("uv sync --frozen", setup)
        self.assertIn(".venv/bin/python", setup)
        self.assertIn("import flask, typer", setup)
        self.assertIn("remove_systemd_units", setup)

    def test_install_update_reinstalls_systemd_units_cleanly(self):
        setup = _read("deploy/setup.sh")
        self.assertIn("sudo systemctl disable --now media-web.service media-server.service", setup)
        self.assertIn("sudo rm -f /etc/systemd/system/media-web.service /etc/systemd/system/media-server.service", setup)
        self.assertIn('actions+=("reinstalled systemd units")', setup)

    def test_deployment_check_uses_project_venv_python(self):
        check = _read("deploy/check_deployment.sh")
        self.assertIn('.venv/bin/python', check)
        self.assertIn('import flask, typer', check)
        self.assertIn('ExecStart', check)
        self.assertIn('WorkingDirectory', check)
        self.assertIn('DEPLOY_ROOT', check)
        self.assertIn('expected="${DEPLOY_ROOT}/.venv/bin/python"', check)

    def test_readme_documents_uv_based_deploy_flow(self):
        readme = _read("README.md")
        self.assertNotIn("python3 -m pip install flask", readme)
        self.assertIn("uv sync", readme)
        self.assertIn(".venv/bin/python", readme)


if __name__ == "__main__":
    unittest.main()
