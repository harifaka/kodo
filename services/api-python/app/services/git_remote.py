"""SaaS / Git adapter (Phase 6): shallow clone into a managed workspace and branch/commit export.

Safety rules:

* Only ``https`` GitHub/GitLab URLs are accepted (no ``ssh``, no ``file://``, no credentials in the
  URL, no shell metacharacters). Every command is a list-argument ``subprocess.run`` with
  ``shell=False``.
* Tokens are passed as transient ``-c http.extraHeader=...`` arguments for a single Git invocation.
  They are never written into ``.git/config``, never used in remote URLs, never logged and never
  returned in a response or an audit entry.
* Clones land in ``KODO_WORKSPACES_DIR`` (default ``~/.kodo/workspaces``) so the target repository
  is never polluted.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.generators.base import kebab_case
from app.patching.paths import PatchRejected, resolve_root
from app.services.audit_log import (
    AUDIT_ACTION_GIT_CLONE,
    AUDIT_ACTION_GIT_EXPORT,
    record_event,
    redact,
)
from app.services.git_errors import GitRemoteError
from app.services.github_client import (
    create_pull_request,
    parse_github_remote,
    set_transport_override,
)

GIT_TIMEOUT_SECONDS = 60
CLONE_TIMEOUT_SECONDS = 300
PUSH_TIMEOUT_SECONDS = 300

_KNOWN_HOSTS = {"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"}
_REPO_PATH = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_FORBIDDEN_URL_CHARS = set("\n\r\t\x00 ;|&`$<>'\"\\")


class GitModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CloneResult(GitModel):
    local_path: str
    repo_url: str
    branch: str | None = None


class ExportResult(GitModel):
    branch: str
    commit_sha: str
    pushed: bool = False
    pr_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


def validate_repo_url(raw: str) -> str:
    """Validate an HTTPS GitHub/GitLab clone URL and reject anything that could be injected."""
    value = (raw or "").strip()
    if not value:
        raise GitRemoteError(400, "INVALID_REPO_URL", "repoUrl is required.")
    if len(value) > 500:
        raise GitRemoteError(400, "INVALID_REPO_URL", "repoUrl is too long.")
    if any(char in _FORBIDDEN_URL_CHARS for char in value):
        raise GitRemoteError(
            400,
            "INVALID_REPO_URL",
            "repoUrl must not contain spaces, quotes or shell metacharacters.",
        )

    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https":
        raise GitRemoteError(
            400,
            "INVALID_REPO_URL",
            "Only https:// GitHub or GitLab repository URLs are supported (ssh and file:// are rejected).",
        )
    if parsed.username or parsed.password:
        raise GitRemoteError(
            400,
            "INVALID_REPO_URL",
            "Do not embed credentials in repoUrl — provide the token separately; Kodo keeps it in memory only.",
        )
    if parsed.query or parsed.fragment:
        raise GitRemoteError(400, "INVALID_REPO_URL", "repoUrl must not contain a query string or fragment.")

    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts():
        raise GitRemoteError(
            400,
            "INVALID_REPO_URL",
            f"Unsupported Git host '{host or '(none)'}'. Allowed hosts: {', '.join(sorted(allowed_hosts()))}.",
        )

    path = parsed.path.rstrip("/").removesuffix(".git")
    if not _REPO_PATH.fullmatch(path):
        raise GitRemoteError(
            400,
            "INVALID_REPO_URL",
            "repoUrl must look like https://github.com/<owner>/<repo>.",
        )
    return f"https://{host}{path}"


def allowed_hosts() -> set[str]:
    configured = os.getenv("KODO_GIT_ALLOWED_HOSTS")
    if not configured:
        return set(_KNOWN_HOSTS)
    extra = {entry.strip().lower() for entry in configured.split(",") if entry.strip()}
    return set(_KNOWN_HOSTS) | extra


def validate_branch_name(raw: str) -> str:
    """Reject anything that is not a plain, safe Git ref name."""
    value = (raw or "").strip()
    if not value or not _BRANCH.fullmatch(value):
        raise GitRemoteError(
            400,
            "INVALID_BRANCH",
            "branchName must start with a letter or digit and contain only letters, digits, '.', "
            "'_' or '-' and '/'.",
        )
    if (
        value.endswith((".", ".lock", "/"))
        or ".." in value
        or "//" in value
        or "@{" in value
        or value.startswith("refs/")
    ):
        raise GitRemoteError(400, "INVALID_BRANCH", f"'{value}' is not a valid Git branch name.")
    return value


def workspaces_dir() -> Path:
    configured = os.getenv("KODO_WORKSPACES_DIR")
    if configured and configured.strip():
        return Path(configured.strip()).expanduser().resolve()
    return (Path.home() / ".kodo" / "workspaces").resolve()


def clone_repository(repo_url: str, *, branch: str | None = None, token: str | None = None) -> CloneResult:
    """Shallow-clone a remote repository into a managed workspace directory."""
    url = validate_repo_url(repo_url)
    branch_name = validate_branch_name(branch) if branch and branch.strip() else None

    base = workspaces_dir()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GitRemoteError(
            500, "WORKSPACE_FAILED", f"Cannot create the Kodo workspaces directory: {exc.strerror or exc}"
        ) from exc

    slug = kebab_case(Path(urlsplit(url).path).name) or "repo"
    target = base / f"{slug}-{uuid.uuid4().hex[:8]}"

    args = ["git", *_auth_args(token), "clone", "--depth", "1", "--single-branch"]
    if branch_name:
        args.extend(["--branch", branch_name])
    args.extend(["--", url, str(target)])

    result = _run(args, cwd=base, timeout=CLONE_TIMEOUT_SECONDS)
    if result is None:
        record_event(AUDIT_ACTION_GIT_CLONE, str(target), "git is not installed", status="failed")
        raise GitRemoteError(503, "GIT_UNAVAILABLE", "Git is not installed or not on PATH.")
    if result.returncode != 0:
        detail = _safe_detail(result.stderr)
        record_event(AUDIT_ACTION_GIT_CLONE, str(target), f"Clone failed: {detail}", status="failed")
        raise GitRemoteError(
            502,
            "CLONE_FAILED",
            f"git clone failed. {detail}" if detail else "git clone failed.",
        )

    checked_out = _current_branch(target) or branch_name
    record_event(
        AUDIT_ACTION_GIT_CLONE,
        str(target),
        f"Cloned {urlsplit(url).netloc}{urlsplit(url).path} "
        f"(branch {checked_out or 'default'})",
    )
    return CloneResult(local_path=str(target), repo_url=url, branch=checked_out)


def export_branch(
    root_path: str,
    *,
    branch_name: str,
    commit_message: str,
    create_pr: bool = False,
    pr_title: str | None = None,
    pr_body: str | None = None,
    token: str | None = None,
) -> ExportResult:
    """Create/switch a branch, commit the applied changes and optionally open a GitHub PR."""
    try:
        root = resolve_root(root_path)
    except PatchRejected as exc:
        raise GitRemoteError(exc.status_code, "PATH_REJECTED", str(exc)) from exc

    branch = validate_branch_name(branch_name)
    message = _validate_commit_message(commit_message)

    if not _is_git_repo(root):
        raise GitRemoteError(
            400, "NOT_A_GIT_REPO", "The workspace root is not a Git repository, so it cannot be exported."
        )

    try:
        return _export(root, branch, message, create_pr, pr_title, pr_body, token)
    except GitRemoteError as exc:
        record_event(
            AUDIT_ACTION_GIT_EXPORT,
            str(root),
            f"Export of branch {branch} failed ({exc.code}): {exc}",
            status="failed",
        )
        raise


def _export(
    root: Path,
    branch: str,
    message: str,
    create_pr: bool,
    pr_title: str | None,
    pr_body: str | None,
    token: str | None,
) -> ExportResult:
    warnings: list[str] = []
    base_branch = _current_branch(root)
    _switch_branch(root, branch)

    status = _git_checked(root, "status", "--porcelain").stdout
    changed = [line for line in status.splitlines() if line.strip()]

    if changed:
        _git_checked(root, "add", "-A")
        _git_checked(root, "commit", "-m", message)
    else:
        warnings.append("No changes to commit; the branch points at the existing HEAD commit.")

    commit_sha = _git_checked(root, "rev-parse", "HEAD").stdout.strip()
    pushed = False
    pr_url: str | None = None

    if create_pr:
        remote = github_remote(root)
        if not token:
            warnings.append(
                "A GitHub token is required to push and open a pull request; the branch and commit "
                "were created locally only."
            )
        elif remote is None:
            warnings.append(
                "The 'origin' remote is not a GitHub repository; the branch and commit were created "
                "locally only."
            )
        else:
            owner, repo = remote
            push = _run(
                ["git", *_auth_args(token), "push", "-u", "origin", branch],
                cwd=root,
                timeout=PUSH_TIMEOUT_SECONDS,
            )
            if push is None:
                raise GitRemoteError(503, "GIT_UNAVAILABLE", "Git is not installed or not on PATH.")
            if push.returncode != 0:
                raise GitRemoteError(
                    502,
                    "PUSH_FAILED",
                    f"git push failed. {_safe_detail(push.stderr)}".strip(),
                )
            pushed = True
            pr_url = create_pull_request(
                owner=owner,
                repo=repo,
                head=branch,
                base=base_branch or "main",
                title=(pr_title or message.splitlines()[0])[:250],
                body=pr_body or "",
                token=token,
            )

    record_event(
        AUDIT_ACTION_GIT_EXPORT,
        str(root),
        f"Exported branch {branch} at {commit_sha[:7] or 'HEAD'}"
        + (f" (pull request {pr_url})" if pr_url else "")
        + (f" from {base_branch}" if base_branch else ""),
        files_count=len(changed),
    )
    return ExportResult(
        branch=branch,
        commit_sha=commit_sha,
        pushed=pushed,
        pr_url=pr_url,
        warnings=warnings,
    )


def github_remote(root: Path) -> tuple[str, str] | None:
    result = _run(["git", "remote", "get-url", "origin"], cwd=root, timeout=GIT_TIMEOUT_SECONDS)
    if result is None or result.returncode != 0:
        return None
    return parse_github_remote(result.stdout)


def _validate_commit_message(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise GitRemoteError(400, "INVALID_COMMIT_MESSAGE", "commitMessage is required.")
    if len(value) > 500 or "\x00" in value:
        raise GitRemoteError(
            400, "INVALID_COMMIT_MESSAGE", "commitMessage must be 500 characters or fewer."
        )
    return value


def _auth_args(token: str | None) -> list[str]:
    """Build transient ``-c http.extraHeader=...`` args; nothing is written to .git/config."""
    if not token or not token.strip():
        return []
    encoded = base64.b64encode(f"x-access-token:{token.strip()}".encode()).decode("ascii")
    return ["-c", f"http.extraHeader=Authorization: Basic {encoded}"]


def _is_git_repo(root: Path) -> bool:
    probe = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, timeout=GIT_TIMEOUT_SECONDS)
    return probe is not None and probe.returncode == 0 and probe.stdout.strip() == "true"


def _current_branch(root: Path) -> str | None:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, timeout=GIT_TIMEOUT_SECONDS)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return None if not value or value == "HEAD" else value


def _switch_branch(root: Path, branch: str) -> None:
    exists = _run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if exists is not None and exists.returncode == 0:
        _git_checked(root, "checkout", branch)
        return
    _git_checked(root, "checkout", "-b", branch)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    return _run(["git", *args], cwd=root, timeout=GIT_TIMEOUT_SECONDS)


def _git_checked(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = _git(root, *args)
    if result is None:
        raise GitRemoteError(503, "GIT_UNAVAILABLE", "Git is not installed or not on PATH.")
    if result.returncode != 0:
        detail = _safe_detail(result.stderr) or f"exit code {result.returncode}"
        raise GitRemoteError(502, "GIT_FAILED", f"git {args[0]} failed: {detail}")
    return result


def _run(args: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str] | None:
    """Single Git subprocess seam: list args, ``shell=False``, prompts disabled, hard timeout."""
    try:
        return subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=_git_env(),
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise GitRemoteError(504, "GIT_TIMEOUT", f"git did not finish within {timeout}s.") from exc
    except OSError as exc:
        raise GitRemoteError(502, "GIT_FAILED", f"Could not run Git: {exc}") from exc


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    return env


def _safe_detail(text: str) -> str:
    """Short, token-free snippet of Git stderr suitable for a UI message."""
    cleaned = redact((text or "").strip())
    return cleaned[:400] + (" …" if len(cleaned) > 400 else "")


__all__ = [
    "CloneResult",
    "ExportResult",
    "GitRemoteError",
    "allowed_hosts",
    "clone_repository",
    "export_branch",
    "github_remote",
    "set_transport_override",
    "validate_branch_name",
    "validate_repo_url",
    "workspaces_dir",
]
