"""Local JSON storage and repository identity; no network or model calls."""

from contextlib import contextmanager
from pathlib import Path
import fcntl
import json
import os
import re
import subprocess
import tempfile
import time
import uuid


class Error(Exception):
    pass


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise Error("Invalid identifier")
    return value


def uid(prefix):
    return prefix + uuid.uuid4().hex[:12]


def load_json(path, default=None):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        if default is not None:
            return default
        raise Error(f"State file missing: {path}") from None
    except (ValueError, UnicodeError) as exc:
        raise Error(f"Invalid JSON in {path}: {exc}; existing data was not reset") from None


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(path, timeout=10):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Error(f"Local state is busy: {path}; retry after the writer finishes") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def git(repo, *args):
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        env.pop(key, None)
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                                text=True, env=env, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise Error(f"Cannot inspect Git repository: {exc}") from None
    return result.stdout.strip() if result.returncode == 0 else None


class Store:
    def __init__(self, home=None, repo=None, project_root=None):
        self.home = Path(home or os.environ.get("BRANCHBACK_HOME", "~/.branchback")).expanduser().resolve()
        self.repo = Path(repo or os.getcwd()).expanduser().resolve()
        if project_root:
            root = Path(project_root).expanduser().resolve()
            if not root.is_dir():
                raise Error("--project-root must be an existing directory")
            self.key, self.name = "dir:" + str(root), root.name
            self.worktree = root
            self.is_git = False
        else:
            common = git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if common is None:
                raise Error("No Git repository found; use --project-root for an explicit non-Git project")
            common = Path(common).resolve()
            self.key = str(common)
            self.name = common.parent.name if common.name == ".git" else common.name.removesuffix(".git")
            top = git(self.repo, "rev-parse", "--show-toplevel")
            self.worktree = Path(top).resolve() if top else self.repo
            self.is_git = True

    def registry(self):
        registry = load_json(self.home / "projects.json", {})
        if not isinstance(registry, dict):
            raise Error("projects.json must be a repository-to-directory object")
        for key, value in registry.items():
            if not isinstance(key, str) or not isinstance(value, str) or not re.fullmatch(r"projects/[a-z0-9-]+", value):
                raise Error("Invalid projects.json entry; refusing to guess or overwrite it")
        return registry

    def project(self, create=False):
        if create:
            with locked(self.home / ".projects.lock"):
                registry = self.registry()
                if self.key not in registry:
                    name = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")[:40] or "project"
                    while True:
                        relative = "projects/" + name + "-" + uuid.uuid4().hex[:8]
                        directory = self.home / relative
                        if not directory.exists():
                            break
                    directory.mkdir(parents=True)
                    registry[self.key] = relative
                    atomic_json(self.home / "projects.json", registry)
                project = self.home / registry[self.key]
                if not project.is_dir():
                    raise Error(f"Registered project directory is missing: {project}")
                return project
        relative = self.registry().get(self.key)
        if relative is None:
            return None
        path = self.home / relative
        if not path.is_dir():
            raise Error(f"Registered project directory is missing: {path}")
        return path

    def rebind(self, old_key):
        with locked(self.home / ".projects.lock"):
            registry = self.registry()
            if old_key not in registry:
                raise Error("The old repository key is not registered")
            if self.key in registry and self.key != old_key:
                raise Error("Current repository already has a project; automatic merging is unsupported")
            relative = registry.pop(old_key)
            if not (self.home / relative).is_dir():
                raise Error("The old project state directory is missing")
            registry[self.key] = relative
            atomic_json(self.home / "projects.json", registry)
            return {"repository": self.key, "state_directory": str(self.home / relative)}

    def provenance(self):
        if not self.is_git:
            return {"worktree": str(self.worktree), "head": None, "dirty": None}
        status = git(self.repo, "status", "--porcelain")
        return {"worktree": str(self.worktree),
                "head": git(self.repo, "rev-parse", "--verify", "HEAD"),
                "dirty": bool(status) if status is not None else None}

    def tree_path(self, tree_id):
        project = self.project()
        if project is None:
            raise Error("Project is not registered; use start to create an exploration")
        return project / "trees" / (identifier(tree_id) + ".json")

    def read_tree(self, tree_id):
        tree = load_json(self.tree_path(tree_id))
        if not isinstance(tree, dict) or tree.get("schema") not in (1, 2) or tree.get("id") != tree_id:
            raise Error("Unsupported or invalid exploration state")
        for key in ("nodes", "sessions"):
            if not isinstance(tree.get(key), dict):
                raise Error(f"Invalid exploration {key}")
        return tree

    def list_trees(self):
        project = self.project()
        if project is None:
            return {"repository": self.key, "state_directory": None, "trees": []}
        trees = []
        for path in sorted((project / "trees").glob("*.json")):
            tree = self.read_tree(path.stem)
            trees.append({"id": tree["id"], "goal": tree["nodes"][tree["root"]]["question"],
                          "status": tree["status"], "updated_at": tree["updated_at"],
                          "sessions": [{"id": s["id"], "label": s["label"], "node": s["node"],
                                        "status": s["status"]} for s in tree["sessions"].values()]})
        return {"repository": self.key, "state_directory": str(project), "trees": trees}

    @contextmanager
    def transaction(self, tree_id):
        path = self.tree_path(tree_id)
        with locked(path.with_suffix(".lock")):
            tree = self.read_tree(tree_id)
            yield tree
            # Older readers must not write trees containing the new lifecycle states.
            # Upgrade only on successful writes; historical nodes/events stay intact.
            tree["schema"] = 2
            atomic_json(path, tree)
