from __future__ import annotations

import argparse
import hashlib
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCRIPT_FOLDER_NAME = "AbletonMCP"
SCRIPT_FILE_NAME = "__init__.py"


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def get_repo_remote_script_source_path() -> Path:
    return get_repo_root() / "AbletonMCP_Remote_Script" / SCRIPT_FILE_NAME


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_macos_user_remote_script_dirs(home: Optional[Path] = None) -> List[Path]:
    base_home = Path(home).expanduser() if home is not None else Path.home()
    base_dir = base_home / "Library" / "Preferences" / "Ableton"
    if not base_dir.is_dir():
        return []
    return sorted(
        path for path in base_dir.glob("Live */User Remote Scripts")
        if path.is_dir()
    )


def discover_macos_remote_script_targets(
    home: Optional[Path] = None,
    script_name: str = SCRIPT_FOLDER_NAME,
) -> List[Path]:
    return [
        root / script_name / SCRIPT_FILE_NAME
        for root in discover_macos_user_remote_script_dirs(home=home)
    ]


def expected_macos_remote_script_target(
    live_version: str,
    home: Optional[Path] = None,
    script_name: str = SCRIPT_FOLDER_NAME,
) -> Path:
    base_home = Path(home).expanduser() if home is not None else Path.home()
    return (
        base_home
        / "Library"
        / "Preferences"
        / "Ableton"
        / ("Live {0}".format(live_version))
        / "User Remote Scripts"
        / script_name
        / SCRIPT_FILE_NAME
    )


def detect_running_ableton_app_path_macos() -> Optional[Path]:
    if platform.system() != "Darwin":
        return None
    result = subprocess.run(
        ["ps", "-axo", "command"],
        check=False,
        capture_output=True,
        text=True,
    )
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if "Ableton Live" not in line or "/Contents/MacOS/Live" not in line:
            continue
        prefix = line.split("/Contents/MacOS/Live", 1)[0].strip()
        if prefix.endswith(".app"):
            return Path(prefix)
    return None


def detect_running_live_version_macos() -> Optional[str]:
    app_path = detect_running_ableton_app_path_macos()
    if app_path is None:
        return None
    result = subprocess.run(
        ["mdls", "-name", "kMDItemVersion", "-raw", str(app_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    raw = result.stdout.strip().strip('"')
    match = re.match(r"([0-9]+(?:\.[0-9]+)+)", raw)
    return match.group(1) if match else None


def sync_remote_script_targets(
    source_path: Optional[Path] = None,
    targets: Optional[Iterable[Path]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    source = Path(source_path) if source_path is not None else get_repo_remote_script_source_path()
    if not source.is_file():
        raise FileNotFoundError("Remote Script source not found: {0}".format(source))

    candidate_targets = [Path(target).expanduser() for target in (targets or discover_macos_remote_script_targets())]
    source_sha256 = sha256_file(source)
    target_results: List[Dict[str, Any]] = []

    for target in candidate_targets:
        existed_before = target.is_file()
        installed_sha256 = sha256_file(target) if existed_before else None
        changed = installed_sha256 != source_sha256
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            if changed:
                shutil.copy2(str(source), str(target))
                installed_sha256 = sha256_file(target)

        target_results.append({
            "target_path": str(target),
            "exists_before": existed_before,
            "changed": changed,
            "installed_sha256": installed_sha256,
        })

    return {
        "source_path": str(source),
        "source_sha256": source_sha256,
        "target_count": len(target_results),
        "changed_count": sum(1 for item in target_results if item["changed"]),
        "dry_run": dry_run,
        "targets": target_results,
    }


def _format_sync_result(result: Dict[str, Any]) -> str:
    lines = [
        "Source: {0}".format(result["source_path"]),
        "SHA256: {0}".format(result["source_sha256"]),
        "Targets: {0}".format(result["target_count"]),
        "Changed: {0}".format(result["changed_count"]),
    ]
    for target in result["targets"]:
        status = "would-update" if result["dry_run"] and target["changed"] else "up-to-date"
        if not result["dry_run"] and target["changed"]:
            status = "updated"
        if not target["exists_before"]:
            status = "would-create" if result["dry_run"] else "created"
        lines.append("{0}: {1}".format(status, target["target_path"]))
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sync the AbletonMCP Remote Script into Ableton's user install paths.")
    parser.add_argument("--dry-run", action="store_true", help="Print the target paths and whether they would change.")
    args = parser.parse_args(argv)

    if platform.system() != "Darwin":
        print("This installer currently supports macOS only.", file=sys.stderr)
        return 1

    targets = discover_macos_remote_script_targets()
    if not targets:
        print("No Ableton User Remote Scripts directories were found.", file=sys.stderr)
        return 1

    result = sync_remote_script_targets(dry_run=args.dry_run, targets=targets)
    print(_format_sync_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
