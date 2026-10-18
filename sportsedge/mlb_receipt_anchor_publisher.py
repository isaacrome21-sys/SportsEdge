"""Records-branch publisher for receipt anchors -- Option A (owner decision).

The owner decision (Oct 13, 2026, by delegation; memo
``ANCHOR_HOST_DECISION.md``) chose: anchor target = the
``records/evidence-anchors`` branch of this repository, cadence = daily
roll-up, writer = the established push-driver path. This module implements
the :class:`~sportsedge.mlb_receipt_anchor.ReceiptAnchorPublisher` protocol
against that target. It ships behind the same flag as the anchor module:
:func:`sportsedge.mlb_receipt_anchor.publish_receipt_anchor` refuses while
``ANCHORING_ENABLED`` is False, and that flip is a separate reviewed change
that has NOT been made. Nothing here is invoked by any capture path.

Publication shape (all content lives under ``anchors/`` on the branch, so
the series never collides with the code tree the records branch carries):

* ``anchors/<YYYY-MM-DD>/<system>.json`` -- one payload file per anchor,
  bytes = the canonical serialization of the prepared payload. Payloads
  are content-addressed (``anchor_id``); the bytes are never edited after
  preparation -- a publication that does not verify is a failure, never a
  retry with altered content.
* ``anchors/index.json`` -- the series registry
  (``EVIDENCE_ANCHOR_INDEX_V1``): one entry per anchor with its identity
  facts and, once known, its publication receipt (introducing commit SHA +
  that commit's GitHub-side time). The index update necessarily lags the
  payload commit by one commit: the receipt names the commit that
  introduced the payload, which exists only after that commit lands.
  ``publish`` performs both commits and verifies both from the remote
  before returning a receipt; a half-published state (payload present,
  index incomplete) is a named failure and a later ``publish`` of the
  same payload completes the index from the original introducing commit
  rather than re-committing the payload.
* ``anchors/README.md`` / ``anchors/CADENCE.md`` -- the series' purpose,
  honest limits, and cadence registration (created at series init).

Receipt semantics: ``published_at_utc`` is the committer time of the
introducing commit as fetched back from the remote. Commits on the
records branch are created through GitHub's API by the push path, so
that time is assigned by GitHub at creation -- the project's standing
"commit SHA + GitHub-generated receipt" standard (the same standard the
G2 preregistration records branches were verified under). The publisher
re-reads the payload bytes and the index FROM THE REMOTE after every
commit and refuses (by error name) if what landed is not what was
prepared.

Extending the series: payload schemas are per-system siblings. Only
``MLB_RECEIPT_JOURNAL_ANCHOR_V1`` is registered today; the starter
manifest and Form 2 manifest-digest anchors join by adding a registry
entry and their own payload schema -- the carrier (this publisher, the
index format, the branch) does not change.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .mlb_receipt_anchor import _anchor_id
from .mlb_source import MLBSourceError

ANCHOR_BRANCH = "records/evidence-anchors"
REPO_SLUG = "isaacrome21-sys/SportsEdge"
INDEX_SCHEMA = "EVIDENCE_ANCHOR_INDEX_V1"
INDEX_PATH = "anchors/index.json"
README_PATH = "anchors/README.md"
CADENCE_PATH = "anchors/CADENCE.md"
SERIES_PREFIX = "anchors/"

# Payload schema -> (system slug used in paths and index entries).
# One entry per archive family; the carrier is shared, payloads are siblings.
SYSTEM_REGISTRY: dict[str, str] = {
    "MLB_RECEIPT_JOURNAL_ANCHOR_V1": "mlb-receipt-journal",
}


def canonical_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    """The exact bytes committed for ``payload`` (stable across writers)."""
    return (json.dumps(dict(payload), sort_keys=True, indent=2) + "\n").encode()


def empty_index() -> dict[str, Any]:
    return {
        "schema": INDEX_SCHEMA,
        "series": ANCHOR_BRANCH,
        "entries": [],
    }


def build_series_readme() -> str:
    return (
        "# Evidence anchor series\n"
        "\n"
        "This branch carries the SportsEdge evidence anchor series: small\n"
        "content-addressed payloads, one per anchored archive state, plus\n"
        "the series registry at `anchors/index.json`. Anchors are the\n"
        "project's external timestamp for its evidence archives (the MLB\n"
        "receipt journal today; sibling payload schemas for the starter\n"
        "manifest and the CFB Form 2 archive join the same series).\n"
        "\n"
        "## What an anchor proves -- and what it does not\n"
        "\n"
        "An anchor proves **existence-by-publication-time only**: the\n"
        "archive state named by the payload's identity fields (chain head\n"
        "hash, genesis, sequence range, entry count, whole-file SHA-256)\n"
        "existed, byte-for-byte, at or before the GitHub publication\n"
        "receipt time of the commit that introduced the payload.\n"
        "\n"
        "An anchor does **not** prove that any individual record inside\n"
        "the archive was captured when it claims, does not prove the\n"
        "history accumulated gradually (only the cadence of anchors\n"
        "bounds that, prospectively), and is **not** a cryptographic\n"
        "signature or attestation. It carries no promotion authority and\n"
        "authorizes no activation of anything.\n"
        "\n"
        "Material written before this series began keeps the status it\n"
        "already carries: locally consistent, externally **UNANCHORED**.\n"
        "A first anchor gives pre-anchor history an upper bound on its\n"
        "existence; it does not retroactively verify it, and the\n"
        "UNANCHORED labels on pre-anchor records stay as written.\n"
    )


def build_series_cadence() -> str:
    return (
        "# Anchor cadence registration\n"
        "\n"
        "Cadence: **daily roll-up** -- each active system's current head\n"
        "is anchored once per capture day, and additionally at any cohort\n"
        "boundary (activation day, freeze change). The rewrite window an\n"
        "anchor leaves open equals the cadence interval; daily bounds it\n"
        "to at most 24 hours of captures.\n"
        "\n"
        "Writer: the records-branch publisher\n"
        "(`sportsedge/mlb_receipt_anchor_publisher.py`) through the\n"
        "established push-driver path; each publication surfaces the\n"
        "driver's runtime approval card.\n"
        "\n"
        "Missed-window rule: if a day's anchor is late or skipped, the\n"
        "gap is visible in the series' dates and is recovered by\n"
        "publishing at the next window with its true (later) receipt\n"
        "time. **Never backfill a fabricated earlier receipt.** Records\n"
        "in the gap are bounded only by the next anchor.\n"
        "\n"
        "Host downtime defers publication; preparation is local and\n"
        "queues. Captures never wait on publication: a failed or skipped\n"
        "anchor degrades the evidence bound, never the capture.\n"
    )


class AnchorTransport(Protocol):
    """Remote-branch transport seam (tests inject an in-memory fake).

    All reads are from the REMOTE state (post-fetch), never from a local
    checkout's working tree.
    """

    def read_remote_file(self, branch: str, path: str) -> bytes | None:
        """Bytes of ``path`` at the branch head, or None if absent."""
        ...

    def read_remote_head(self, branch: str) -> tuple[str, str] | None:
        """(commit SHA, committer time ISO) of the branch head, or None."""
        ...

    def list_remote_files(self, branch: str, prefix: str) -> list[str]:
        """All file paths under ``prefix`` at the branch head."""
        ...

    def history_for_path(self, branch: str, path: str) -> list[tuple[str, str]]:
        """(commit SHA, committer time ISO) that touched ``path``,
        oldest first; the first entry introduced the file."""
        ...

    def push_files(self, branch: str, files: Mapping[str, str], message: str) -> None:
        """Commit ``files`` (path -> text content) onto ``branch`` via the
        established push path. ``files`` must be the branch's complete
        anchor-owned set (everything under ``anchors/``): the push path
        composes from the given files, so a partial set would drop
        earlier series files."""
        ...


class PushDriverTransport:
    """Default transport: git reads against the local clone (post-fetch)
    and writes through ``~/workspace/push_files_driver.py`` -- the same
    path that published the G2 preregistration records branches."""

    def __init__(self, repo_dir: str | Path, driver_path: str | Path,
                 owner: str, repo: str):
        self.repo_dir = Path(repo_dir)
        self.driver_path = Path(driver_path)
        self.owner = owner
        self.repo = repo

    # -- git plumbing -----------------------------------------------------
    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.repo_dir,
                              capture_output=True, text=True, check=check)

    def _fetch(self, branch: str) -> bool:
        r = self._git("fetch", "origin", branch, check=False)
        return r.returncode == 0

    # -- reads ------------------------------------------------------------
    def read_remote_file(self, branch: str, path: str) -> bytes | None:
        if not self._fetch(branch):
            return None
        ref = f"origin/{branch}"
        probe = self._git("cat-file", "-e", f"{ref}:{path}", check=False)
        if probe.returncode != 0:
            return None
        r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=self.repo_dir,
                           capture_output=True, check=True)
        return r.stdout

    def read_remote_head(self, branch: str) -> tuple[str, str] | None:
        if not self._fetch(branch):
            return None
        r = self._git("log", "-1", "--format=%H%x20%cI", f"origin/{branch}",
                      check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        sha, _, when = r.stdout.strip().partition(" ")
        return sha, when

    def list_remote_files(self, branch: str, prefix: str) -> list[str]:
        if not self._fetch(branch):
            return []
        r = self._git("ls-tree", "-r", "--name-only", f"origin/{branch}",
                      "--", prefix, check=False)
        if r.returncode != 0:
            return []
        return [ln for ln in r.stdout.splitlines() if ln.strip()]

    def history_for_path(self, branch: str, path: str) -> list[tuple[str, str]]:
        if not self._fetch(branch):
            return []
        r = self._git("log", "--reverse", "--format=%H%x20%cI",
                      f"origin/{branch}", "--", path, check=False)
        if r.returncode != 0:
            return []
        out = []
        for ln in r.stdout.splitlines():
            sha, _, when = ln.strip().partition(" ")
            if sha:
                out.append((sha, when))
        return out

    # -- write ------------------------------------------------------------
    def push_files(self, branch: str, files: Mapping[str, str], message: str) -> None:
        exists = self._fetch(branch)
        base = f"origin/{branch}" if exists else "origin/main"
        scratch = f"scratch/anchor-publish-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}"
        tmp = Path(tempfile.mkdtemp(prefix="anchor-publish-"))
        worktree = tmp / "wt"
        try:
            self._git("worktree", "add", "-b", scratch, str(worktree), base)
            for path, content in files.items():
                dest = worktree / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content)
            self._git("-C", str(worktree), "add", "--", *files.keys())
            self._git("-C", str(worktree), "commit", "-m", message)
            head = self._git("-C", str(worktree), "rev-parse", "HEAD").stdout.strip()
            r = subprocess.run(
                ["python3", str(self.driver_path), self.owner, self.repo,
                 branch, head, message, *files.keys()],
                capture_output=True, text=True)
            if r.returncode != 0 or "ALL PUSHED" not in r.stdout:
                raise MLBSourceError(
                    "RECEIPT_ANCHOR_PUBLICATION_TRANSPORT_FAILED:"
                    + (r.stdout.strip().splitlines() or ["driver"])[-1][:120])
        finally:
            self._git("worktree", "remove", "--force", str(worktree), check=False)
            self._git("branch", "-D", scratch, check=False)


class RecordsBranchPublisher:
    """The Option A publisher: commits anchor payloads to
    ``records/evidence-anchors`` and returns GitHub's receipt.

    A receipt is returned only after the payload bytes and the index
    entry have been re-read FROM THE REMOTE and match what was prepared.
    Any mismatch raises by name; the payload is never edited and never
    re-committed to fix a verification failure -- a later ``publish`` of
    the same payload completes only the index, from the original
    introducing commit.
    """

    def __init__(self, transport: AnchorTransport | None = None, *,
                 branch: str = ANCHOR_BRANCH,
                 clock: Callable[[], datetime] | None = None):
        if transport is None:
            owner, repo = REPO_SLUG.split("/", 1)
            transport = PushDriverTransport(
                repo_dir="/home/hatch/workspace/tmpgit/sportsedge-ci",
                driver_path="/home/hatch/workspace/push_files_driver.py",
                owner=owner, repo=repo)
        self.transport = transport
        self.branch = branch
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # -- series helpers ---------------------------------------------------
    def _location(self, path: str, sha: str) -> str:
        return f"https://github.com/{REPO_SLUG}/blob/{self.branch}/{path}@{sha}"

    def _load_index(self) -> dict[str, Any]:
        raw = self.transport.read_remote_file(self.branch, INDEX_PATH)
        if raw is None:
            raise MLBSourceError("RECEIPT_ANCHOR_SERIES_NOT_INITIALIZED")
        try:
            index = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise MLBSourceError("RECEIPT_ANCHOR_INDEX_INVALID") from exc
        if not isinstance(index, dict) or index.get("schema") != INDEX_SCHEMA \
                or not isinstance(index.get("entries"), list):
            raise MLBSourceError("RECEIPT_ANCHOR_INDEX_INVALID")
        return index

    def _series_files(self) -> dict[str, str]:
        """The complete anchor-owned file set currently on the branch."""
        files: dict[str, str] = {}
        for path in self.transport.list_remote_files(self.branch, SERIES_PREFIX):
            raw = self.transport.read_remote_file(self.branch, path)
            if raw is None:
                raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_TRANSPORT_FAILED:"
                                     f"listed file unreadable: {path}")
            files[path] = raw.decode()
        return files

    def _find_entry(self, index: Mapping[str, Any], anchor_id: str):
        for entry in index.get("entries", []):
            if isinstance(entry, dict) and entry.get("anchor_id") == anchor_id:
                return entry
        return None

    # -- the protocol -----------------------------------------------------
    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        schema = payload.get("schema")
        system = SYSTEM_REGISTRY.get(schema or "")
        if system is None:
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLISHER_SCHEMA_UNSUPPORTED")
        if payload.get("anchor_id") != _anchor_id(payload):
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLISHER_ANCHOR_ID_INVALID")
        anchor_id = payload["anchor_id"]
        data = canonical_payload_bytes(payload)

        if self.transport.read_remote_head(self.branch) is None:
            raise MLBSourceError("RECEIPT_ANCHOR_SERIES_NOT_INITIALIZED")
        index = self._load_index()
        entry = self._find_entry(index, anchor_id)

        if entry is not None:
            path = entry["path"]
            landed = self.transport.read_remote_file(self.branch, path)
            if landed != data:
                raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH")
            publication = entry.get("publication") or {}
            if publication.get("commit_sha"):
                return {"anchor_id": anchor_id,
                        "published_at_utc": publication["published_at_utc"],
                        "location": self._location(path, publication["commit_sha"]),
                        "commit_sha": publication["commit_sha"],
                        "already_anchored": True}
            # Payload landed earlier but the index lag commit did not:
            # complete the index from the ORIGINAL introducing commit.
            history = self.transport.history_for_path(self.branch, path)
            if not history:
                raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH")
            sha1, t1 = history[0]
            return self._complete_index(payload, index, entry, sha1, t1)

        path = (f"anchors/{self.clock():%Y-%m-%d}/{system}.json")
        landed = self.transport.read_remote_file(self.branch, path)
        if landed is not None and landed != data:
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH")
        if landed == data:
            # Same-day payload already on the branch without an index
            # entry (index was behind): recover from its introducing
            # commit instead of re-committing identical bytes.
            history = self.transport.history_for_path(self.branch, path)
            if not history:
                raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH")
            sha1, t1 = history[0]
            new_entry = self._new_entry(payload, system, path)
            index["entries"].append(new_entry)
            return self._complete_index(payload, index, new_entry, sha1, t1)

        new_entry = self._new_entry(payload, system, path)
        files = self._series_files()
        files[path] = data.decode()
        index["entries"].append(new_entry)
        files[INDEX_PATH] = json.dumps(index, sort_keys=True, indent=2) + "\n"
        message = (f"anchor: {system} {anchor_id[:12]} "
                   f"seq {payload.get('journal_first_sequence')}"
                   f"-{payload.get('journal_last_sequence')}")
        self.transport.push_files(self.branch, files, message)
        head = self.transport.read_remote_head(self.branch)
        if head is None:
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_TRANSPORT_FAILED:"
                                 "no head after payload push")
        sha1, t1 = head
        landed = self.transport.read_remote_file(self.branch, path)
        if landed != data:
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH")
        return self._complete_index(payload, index, new_entry, sha1, t1)

    def _new_entry(self, payload: Mapping[str, Any], system: str, path: str) -> dict[str, Any]:
        return {
            "anchor_id": payload["anchor_id"],
            "system": system,
            "schema": payload["schema"],
            "path": path,
            "receipt_chain_head_sha256": payload.get("receipt_chain_head_sha256"),
            "journal_first_sequence": payload.get("journal_first_sequence"),
            "journal_last_sequence": payload.get("journal_last_sequence"),
            "journal_entry_count": payload.get("journal_entry_count"),
            "journal_sha256": payload.get("journal_sha256"),
            "publication": None,
        }

    def _complete_index(self, payload: Mapping[str, Any], index: dict[str, Any],
                        entry: dict[str, Any], sha1: str, t1: str) -> dict[str, Any]:
        """Lag commit: record the introducing commit in the index, then
        verify the index FROM THE REMOTE before returning the receipt."""
        entry["publication"] = {"commit_sha": sha1, "published_at_utc": t1}
        files = self._series_files()
        files[INDEX_PATH] = json.dumps(index, sort_keys=True, indent=2) + "\n"
        self.transport.push_files(self.branch, files,
                                  f"anchor index: {payload['anchor_id'][:12]} published")
        raw = self.transport.read_remote_file(self.branch, INDEX_PATH)
        try:
            landed_index = json.loads((raw or b"").decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise MLBSourceError(
                "RECEIPT_ANCHOR_PUBLICATION_INDEX_INCOMPLETE") from exc
        landed_entry = self._find_entry(landed_index, payload["anchor_id"])
        publication = (landed_entry or {}).get("publication") or {}
        if publication.get("commit_sha") != sha1:
            raise MLBSourceError("RECEIPT_ANCHOR_PUBLICATION_INDEX_INCOMPLETE")
        return {"anchor_id": payload["anchor_id"],
                "published_at_utc": t1,
                "location": self._location(entry["path"], sha1),
                "commit_sha": sha1}
