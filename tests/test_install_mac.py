from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY_ROOT / "install-mac.sh"


def _executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_tools(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    python_marker = tmp_path / "python-venv-created"
    pip_marker = tmp_path / "package-installed"
    npm_ci_marker = tmp_path / "npm-ci-ran"
    npm_build_marker = tmp_path / "npm-build-ran"
    fake_python = _executable(
        tmp_path / "fake-python3",
        f'''#!/bin/sh
set -eu
if [ "$1" = "-c" ]; then
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  venv="$3"
  mkdir -p "$venv/bin"
  touch "{python_marker}"
  cat > "$venv/bin/python" <<'PYTHON'
#!/bin/sh
set -eu
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  touch "$FAKE_PIP_MARKER"
  printf '%s\\n' '#!/bin/sh' 'exit 0' > "$(dirname "$0")/academia"
  chmod 755 "$(dirname "$0")/academia"
  exit 0
fi
exit 1
PYTHON
  chmod 755 "$venv/bin/python"
  exit 0
fi
exit 1
''',
    )
    fake_npm = _executable(
        tmp_path / "fake-npm",
        f'''#!/bin/sh
set -eu
if [ "$1" = "ci" ]; then
  touch "{npm_ci_marker}"
  exit 0
fi
if [ "$1" = "run" ] && [ "$2" = "build" ]; then
  touch "{npm_build_marker}"
  mkdir -p dist
  printf '%s\\n' '<html>dashboard</html>' > dist/index.html
  exit 0
fi
exit 1
''',
    )
    return fake_python, fake_npm, pip_marker, npm_ci_marker


def _run_installer(tmp_path: Path, *, launcher_content: str | None = None) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if launcher_content is not None:
        (bin_dir / "academia").write_text(launcher_content, encoding="utf-8")
    fake_python, fake_npm, pip_marker, _npm_ci_marker = _fake_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PYTHON_BIN": str(fake_python),
            "NPM_BIN": str(fake_npm),
            "FAKE_PIP_MARKER": str(pip_marker),
            "ACADEMIA_OS_VENV": str(home / "academia-venv"),
            "ACADEMIA_OS_BIN_DIR": str(bin_dir),
            "ACADEMIA_OS_ZSHRC": str(home / ".zshrc"),
        }
    )
    return subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=REPOSITORY_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_mac_installer_creates_launcher_and_builds_dashboard_in_one_run(tmp_path: Path) -> None:
    result = _run_installer(tmp_path)
    home = tmp_path / "home"
    launcher = home / ".local" / "bin" / "academia"
    zshrc = home / ".zshrc"

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "python-venv-created").is_file()
    assert (tmp_path / "package-installed").is_file()
    assert (tmp_path / "npm-ci-ran").is_file()
    assert (tmp_path / "npm-build-ran").is_file()
    assert launcher.is_symlink()
    assert launcher.resolve() == (home / "academia-venv" / "bin" / "academia")
    assert 'export PATH="$HOME/.local/bin:$PATH"' in zshrc.read_text(encoding="utf-8")
    assert "Academia OS is ready" in result.stdout


def test_mac_installer_is_repeatable_without_duplicate_path_entries(tmp_path: Path) -> None:
    first = _run_installer(tmp_path)
    second = _run_installer(tmp_path)
    zshrc = (tmp_path / "home" / ".zshrc").read_text(encoding="utf-8")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert zshrc.count('export PATH="$HOME/.local/bin:$PATH"') == 1


def test_mac_installer_refuses_to_overwrite_existing_launcher(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, launcher_content="#!/bin/sh\necho unrelated\n")
    launcher = tmp_path / "home" / ".local" / "bin" / "academia"

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert launcher.read_text(encoding="utf-8") == "#!/bin/sh\necho unrelated\n"
