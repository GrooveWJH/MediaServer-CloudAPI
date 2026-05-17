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

    def test_media_server_service_limits_restart_and_io_priority(self):
        service = _read("deploy/media-server.service")
        self.assertIn("RestartSec=10", service)
        self.assertIn("StartLimitIntervalSec=300", service)
        self.assertIn("StartLimitBurst=3", service)
        self.assertIn("Nice=10", service)
        self.assertIn("IOSchedulingClass=best-effort", service)
        self.assertIn("IOSchedulingPriority=7", service)

    def test_setup_script_bootstraps_uv_and_syncs_dependencies(self):
        setup = _read("deploy/setup.sh")
        self.assertIn("command -v python3", setup)
        self.assertIn("command -v uv", setup)
        self.assertIn("astral.sh/uv/install.sh", setup)
        self.assertIn('sudo chown -R "${user_name}:${user_name}" "${target_root}/.venv"', setup)
        self.assertIn('sudo rm -rf "${target_root}/.venv"', setup)
        self.assertIn('stale virtual environment is not accessible', setup)
        self.assertIn("uv sync --frozen", setup)
        self.assertIn(".venv/bin/python", setup)
        self.assertIn("import flask, typer", setup)
        self.assertIn("remove_systemd_units", setup)

    def test_install_update_reinstalls_systemd_units_cleanly(self):
        setup = _read("deploy/setup.sh")
        self.assertIn("sudo systemctl disable --now media-web.service media-server.service", setup)
        self.assertIn("sudo rm -f /etc/systemd/system/media-web.service /etc/systemd/system/media-server.service", setup)
        self.assertIn('actions+=("reinstalled systemd units")', setup)
        self.assertIn('local log_level="warning"', setup)
        self.assertIn('ENABLE_WEB="false"', setup)
        self.assertIn('--enable-web', setup)
        self.assertIn('docker compose -f "${target_root}/deploy/docker-compose.yml" down', setup)
        self.assertIn("--exclude 'deploy/minio-data/'", setup)
        self.assertIn("--exclude 'deploy/.mc/'", setup)

    def test_setup_script_defaults_web_to_disabled(self):
        setup = _read("deploy/setup.sh")
        self.assertIn('local web_enabled="${ENABLE_WEB}"', setup)
        self.assertIn('sudo systemctl enable --now media-server.service', setup)
        self.assertIn('sudo systemctl enable media-web.service', setup)
        self.assertIn('if [[ "${web_enabled}" == "true" ]]; then', setup)
        self.assertIn('WEB_ENABLED=${web_enabled}', setup)
        self.assertIn('check_port_available "${web_port}"', setup)
        self.assertIn('mc_container_prefix', setup)
        self.assertIn('args+=(--network host)', setup)

    def test_deployment_check_uses_project_venv_python(self):
        check = _read("deploy/check_deployment.sh")
        self.assertIn('.venv/bin/python', check)
        self.assertIn('import flask, typer', check)
        self.assertIn('ExecStart', check)
        self.assertIn('WorkingDirectory', check)
        self.assertIn('DEPLOY_ROOT', check)
        self.assertIn('expected="${DEPLOY_ROOT}/.venv/bin/python"', check)
        self.assertIn('RestartSec', check)
        self.assertIn('Nice', check)
        self.assertIn('IOSchedulingClass', check)
        self.assertIn('IOSchedulingPriority', check)
        self.assertIn('LOG_LEVEL', check)
        self.assertIn('runtime_label="project virtualenv"', check)
        self.assertIn('bootstrap fallback', check)

    def test_deployment_check_skips_web_when_disabled(self):
        check = _read("deploy/check_deployment.sh")
        self.assertIn('WEB_ENABLED="${WEB_ENABLED:-false}"', check)
        self.assertIn('if [[ "${WEB_ENABLED}" != "true" ]]; then', check)
        self.assertIn('Web service disabled by WEB_ENABLED=false', check)
        self.assertIn('expected_script="${DEPLOY_ROOT}/web/app.py"', check)
        self.assertIn('listener_pid_for_port', check)

    def test_deployment_check_validates_minio_beyond_ready_health(self):
        check = _read("deploy/check_deployment.sh")
        self.assertIn('check_minio_data_access', check)
        self.assertIn('STORAGE_ACCESS_KEY="${STORAGE_ACCESS_KEY:-minioadmin}"', check)
        self.assertIn('STORAGE_SECRET_KEY="${STORAGE_SECRET_KEY:-minioadmin}"', check)
        self.assertIn('mc_container_prefix', check)
        self.assertIn('args+=(--network host)', check)
        self.assertIn('admin info local', check)
        self.assertIn('ls "local/${STORAGE_BUCKET}"', check)
        self.assertIn('MinIO IAM/API access OK', check)
        self.assertIn('MinIO bucket access OK', check)

    def test_readme_documents_uv_based_deploy_flow(self):
        readme = _read("README.md")
        self.assertNotIn("python3 -m pip install flask", readme)
        self.assertIn("uv sync", readme)
        self.assertIn(".venv/bin/python", readme)
        self.assertIn("LOG_LEVEL=warning", readme)
        self.assertIn("./deploy/setup.sh --enable-web", readme)
        self.assertIn("默认不启用 Web", readme)
        self.assertIn("WEB_ENABLED=false", readme)


if __name__ == "__main__":
    unittest.main()
