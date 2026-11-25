"""Phase 11: local-only, zero-copy folder browser (``GET /api/v1/fs/browse``).

Every case is hermetic: roots are temporary folders (or monkeypatched module constants for the
Docker mount) and no network, Docker daemon or host folder is required.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt_utils import create_session_token
from app.db import repository
from app.main import app
from app.services import fs_browser


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def browse_root(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    root.mkdir()

    java = root / "alpha-service"
    (java / "src" / "main" / "java").mkdir(parents=True)
    (java / "pom.xml").write_text("<project/>", encoding="utf-8")
    (java / ".git").mkdir()

    node = root / "beta-app"
    node.mkdir()
    (node / "package.json").write_text("{}", encoding="utf-8")

    csharp = root / "gamma-api"
    csharp.mkdir()
    (csharp / "Gamma.Api.csproj").write_text("<Project/>", encoding="utf-8")

    python = root / "delta-py"
    python.mkdir()
    (python / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    # Monorepo parent: no marker files, but real sub-projects underneath.
    monorepo = root / "zeta-monorepo"
    (monorepo / "one" / "src").mkdir(parents=True)

    (root / ".git").mkdir()
    for noise in ("node_modules", "target", "__pycache__", ".venv", "bin", "obj"):
        (root / noise).mkdir()
    return root


@pytest.fixture()
def local_browse_env(
    monkeypatch: pytest.MonkeyPatch,
    browse_root: Path,
    tmp_path: Path,
) -> Iterator[Path]:
    monkeypatch.setenv("KODO_BROWSE_ROOTS", str(browse_root))
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(fs_browser, "detect_runtime", lambda: fs_browser.RUNTIME_NATIVE)
    yield browse_root


@pytest.fixture()
def saas_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("KODO_MODE", "saas")
    monkeypatch.setenv("KODO_JWT_SECRET", "s" * 48)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    yield


# ------------------------------------------------------------------ SaaS lockout


def test_browse_is_always_forbidden_in_saas(client: TestClient, saas_env: None) -> None:
    anonymous = client.get("/api/v1/fs/browse")

    assert anonymous.status_code == 403
    assert anonymous.json()["detail"]["code"] == "FS_BROWSE_DISABLED_IN_SAAS"

    user = repository.upsert_github_user(
        github_id="9101",
        username="tenant",
        display_name="Tenant",
        avatar_url=None,
        email=None,
    )
    token = create_session_token(user.id, user.username)
    authenticated = client.get("/api/v1/fs/browse", headers={"Authorization": f"Bearer {token}"})

    assert authenticated.status_code == 403
    assert authenticated.json()["detail"]["code"] == "FS_BROWSE_DISABLED_IN_SAAS"


# ------------------------------------------------------------- local browsing


def test_browse_lists_sorted_subdirectories_and_skips_noise(
    client: TestClient,
    local_browse_env: Path,
) -> None:
    response = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runtime"] == "native"
    assert body["currentPath"] == str(local_browse_env)
    assert body["parentPath"] is None, "strict roots must not leak the folder above the root"
    assert body["truncated"] is False
    assert body["emptyMountHint"] is False
    assert body["currentMarkers"] == {"stacks": [], "isGitRepo": True}

    names = [entry["name"] for entry in body["entries"]]
    assert names == ["alpha-service", "beta-app", "delta-py", "gamma-api", "zeta-monorepo"]
    for noise in (".git", "node_modules", "target", "__pycache__", ".venv", "bin", "obj"):
        assert noise not in names
    assert [root["path"] for root in body["roots"]] == [str(local_browse_env)]


def test_browse_detects_stack_markers_and_monorepo_subfolders(
    client: TestClient,
    local_browse_env: Path,
) -> None:
    response = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env)})

    assert response.status_code == 200, response.text
    by_name = {entry["name"]: entry for entry in response.json()["entries"]}

    assert by_name["alpha-service"]["stacks"] == ["java"]
    assert by_name["alpha-service"]["isGitRepo"] is True
    assert by_name["alpha-service"]["hasSubdirectories"] is True

    assert by_name["beta-app"]["stacks"] == ["nodejs"]
    assert by_name["beta-app"]["isGitRepo"] is False
    assert by_name["beta-app"]["hasSubdirectories"] is False

    assert by_name["gamma-api"]["stacks"] == ["csharp"]
    assert by_name["delta-py"]["stacks"] == ["python"]

    assert by_name["zeta-monorepo"]["stacks"] == []
    assert by_name["zeta-monorepo"]["hasSubdirectories"] is True


def test_browse_can_drill_down_and_walk_back_up(client: TestClient, local_browse_env: Path) -> None:
    child = local_browse_env / "alpha-service"

    response = client.get("/api/v1/fs/browse", params={"path": str(child)})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currentPath"] == str(child)
    assert body["parentPath"] == str(local_browse_env)
    assert body["currentMarkers"] == {"stacks": ["java"], "isGitRepo": True}
    assert [entry["name"] for entry in body["entries"]] == ["src"]


def test_show_hidden_reveals_noise_folders(client: TestClient, local_browse_env: Path) -> None:
    response = client.get(
        "/api/v1/fs/browse",
        params={"path": str(local_browse_env), "showHidden": "true"},
    )

    assert response.status_code == 200, response.text
    names = [entry["name"] for entry in response.json()["entries"]]
    for noise in (".git", "node_modules", "target", "__pycache__"):
        assert noise in names


# --------------------------------------------------------------- containment


def test_browse_rejects_dotdot_traversal(client: TestClient, local_browse_env: Path) -> None:
    response = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env / "..")})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BROWSE_PATH_OUTSIDE_ROOTS"


def _make_directory_link(link: Path, target: Path) -> bool:
    """Create a directory link without requiring elevation (junction on Windows)."""
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return completed.returncode == 0 and link.exists()
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, subprocess.SubprocessError):
        return False


def test_browse_rejects_symlinks_pointing_outside_the_roots(
    client: TestClient,
    local_browse_env: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    (outside / "secret").mkdir(parents=True)
    link = local_browse_env / "escape"
    if not _make_directory_link(link, outside):
        pytest.skip("This host cannot create directory links without privileges.")

    response = client.get("/api/v1/fs/browse", params={"path": str(link)})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BROWSE_PATH_OUTSIDE_ROOTS"

    listing = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env)})
    assert listing.status_code == 200, listing.text
    assert "escape" not in [entry["name"] for entry in listing.json()["entries"]]


def test_browse_reports_actionable_errors(client: TestClient, local_browse_env: Path) -> None:
    missing = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env / "nope")})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "BROWSE_PATH_NOT_FOUND"

    not_a_directory = client.get(
        "/api/v1/fs/browse",
        params={"path": str(local_browse_env / "beta-app" / "package.json")},
    )
    assert not_a_directory.status_code == 400
    assert not_a_directory.json()["detail"]["code"] == "BROWSE_NOT_A_DIRECTORY"


# ------------------------------------------------------- docker empty mount


def test_docker_empty_mount_returns_a_setup_hint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    # Mirrors the committed `.kodo-empty` placeholder mount: a file, no real subdirectory.
    (projects / ".gitkeep").write_text("", encoding="utf-8")

    monkeypatch.delenv("KODO_BROWSE_ROOTS", raising=False)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(fs_browser, "PROJECTS_MOUNT", projects)
    monkeypatch.setattr(fs_browser, "detect_runtime", lambda: fs_browser.RUNTIME_DOCKER)

    response = client.get("/api/v1/fs/browse")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runtime"] == "docker"
    assert body["currentPath"] == str(projects.resolve())
    assert body["entries"] == []
    assert body["emptyMountHint"] is True
    assert "KODO_LOCAL_PROJECTS_DIR" in body["hintMessage"]
    assert "docker compose up -d" in body["hintMessage"]
    assert [root["path"] for root in body["roots"]] == [str(projects.resolve())]


def test_docker_mount_with_a_project_has_no_empty_hint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    (projects / "alpha-service").mkdir(parents=True)
    (projects / "alpha-service" / "pom.xml").write_text("<project/>", encoding="utf-8")

    monkeypatch.delenv("KODO_BROWSE_ROOTS", raising=False)
    monkeypatch.setenv("KODO_WORKSPACES_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setattr(fs_browser, "PROJECTS_MOUNT", projects)
    monkeypatch.setattr(fs_browser, "detect_runtime", lambda: fs_browser.RUNTIME_DOCKER)

    response = client.get("/api/v1/fs/browse")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["emptyMountHint"] is False
    assert body["hintMessage"] is None
    assert [entry["name"] for entry in body["entries"]] == ["alpha-service"]
    assert body["entries"][0]["stacks"] == ["java"]


# ------------------------------------------------------------- degradation


def test_unreadable_child_directory_is_skipped(
    client: TestClient,
    local_browse_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (local_browse_env / "locked").mkdir()
    original = fs_browser.scan_markers

    def flaky(directory: Path) -> fs_browser.BrowseMarkers:
        if directory.name == "locked":
            raise PermissionError(13, "Permission denied")
        return original(directory)

    monkeypatch.setattr(fs_browser, "scan_markers", flaky)

    response = client.get("/api/v1/fs/browse", params={"path": str(local_browse_env)})

    assert response.status_code == 200, response.text
    names = [entry["name"] for entry in response.json()["entries"]]
    assert "locked" not in names
    assert "alpha-service" in names


def test_missing_configured_roots_answer_with_a_setup_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("KODO_BROWSE_ROOTS", str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(fs_browser, "detect_runtime", lambda: fs_browser.RUNTIME_NATIVE)

    response = client.get("/api/v1/fs/browse")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BROWSE_NO_ROOTS"
