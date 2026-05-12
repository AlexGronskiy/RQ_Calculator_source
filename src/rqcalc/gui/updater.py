from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List


LOG_NAME = "update_log.txt"
STATE_FILE = "update_state.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    if not plan_path.exists():
        return 2

    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    root = Path(plan.get("root_dir") or ".").resolve()
    exe_name = str(plan.get("exe_name") or "RQ_Calc.exe")
    pid = int(plan.get("pid") or 0)

    log_path = root / LOG_NAME

    try:
        log(log_path, "=== START UPDATE ===")
        log(log_path, f"root={root}")
        log(log_path, f"pid={pid}")

        if pid > 0:
            wait_process_exit(pid, timeout_sec=45, log_path=log_path)

        apply_deletes(root, list(plan.get("delete") or []), log_path)

        for comp in list(plan.get("components") or []):
            apply_component(root, comp, log_path)

        state_after = plan.get("state_after")
        if isinstance(state_after, dict):
            (root / STATE_FILE).write_text(
                json.dumps(state_after, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # После успешной установки временный кеш больше не нужен:
        # update_plan.json, downloads/database.sqlite, downloads/app.zip и т.п.
        try:
            cache_dir = plan_path.parent
            if cache_dir.name == ".update_cache" and cache_dir.exists():
                log(log_path, f"cleanup cache dir: {cache_dir}")
                shutil.rmtree(cache_dir, ignore_errors=True)
        except Exception as cleanup_error:
            log(log_path, f"cache cleanup failed: {cleanup_error!r}")

        log(log_path, "=== UPDATE OK ===")
        launch_app(root, exe_name, log_path)
        return 0

    except Exception as e:
        log(log_path, f"ERROR: {e!r}")

        # При ошибке кеш специально НЕ удаляем:
        # там остаются update_plan.json и скачанные файлы,
        # чтобы можно было понять, что пошло не так.
        try:
            launch_app(root, exe_name, log_path)
        except Exception as e2:
            log(log_path, f"LAUNCH AFTER ERROR FAILED: {e2!r}")
        return 1


def wait_process_exit(pid: int, *, timeout_sec: int, log_path: Path) -> None:
    deadline = time.time() + float(timeout_sec)

    while time.time() < deadline:
        if not process_exists(pid):
            log(log_path, "main process exited")
            return
        time.sleep(0.35)

    log(log_path, "main process still alive after timeout; continue anyway")


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False

    if sys.platform.startswith("win"):
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid)
            if handle == 0:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259
        except Exception:
            return True

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def apply_deletes(root: Path, items: List[str], log_path: Path) -> None:
    for rel in items:
        rel = str(rel or "").strip().replace("\\", "/")
        if not rel or rel.startswith("../") or "/../" in rel:
            continue

        target = (root / rel).resolve()
        if not is_inside(root, target):
            continue

        if target.is_dir():
            log(log_path, f"delete dir: {target}")
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            log(log_path, f"delete file: {target}")
            try:
                target.unlink()
            except Exception:
                pass


def apply_component(root: Path, comp: Dict[str, Any], log_path: Path) -> None:
    name = str(comp.get("name") or "component")
    kind = str(comp.get("kind") or "zip").strip().lower()
    source = Path(str(comp.get("source") or "")).resolve()
    target_rel = str(comp.get("target") or ".").strip().replace("\\", "/")

    if not source.exists():
        raise FileNotFoundError(f"source not found for {name}: {source}")

    log(log_path, f"apply {name}: kind={kind}, source={source}, target={target_rel}")

    if kind == "zip":
        apply_zip_component(root, source, target_rel, log_path)
    elif kind == "file":
        apply_file_component(root, source, target_rel, log_path)
    else:
        raise ValueError(f"unknown component kind: {kind}")


def apply_zip_component(root: Path, source: Path, target_rel: str, log_path: Path) -> None:
    extract_dir = source.parent / (source.stem + "_extract")
    if extract_dir.exists():
        shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source, "r") as z:
        z.extractall(extract_dir)

    payload_root = find_payload_root(extract_dir)
    target_root = (root / target_rel).resolve()

    if not is_inside(root, target_root):
        raise RuntimeError(f"bad target path: {target_root}")

    target_root.mkdir(parents=True, exist_ok=True)
    copy_contents(payload_root, target_root, log_path)

    shutil.rmtree(extract_dir, ignore_errors=True)


def apply_file_component(root: Path, source: Path, target_rel: str, log_path: Path) -> None:
    target = (root / target_rel).resolve()
    if not is_inside(root, target):
        raise RuntimeError(f"bad target path: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".new")

    shutil.copy2(source, tmp)
    replace_path(tmp, target)
    log(log_path, f"file replaced: {target}")


def find_payload_root(extract_dir: Path) -> Path:
    items = [p for p in extract_dir.iterdir() if p.name not in ("__MACOSX",)]

    if len(items) == 1 and items[0].is_dir():
        inner = items[0]
        inner_names = {p.name for p in inner.iterdir()}
        if {"RQ_Calc.exe", "_internal", "resources", "rqdata.sqlite"} & inner_names:
            return inner

    return extract_dir


def copy_contents(src_root: Path, dst_root: Path, log_path: Path) -> None:
    for item in src_root.iterdir():
        if item.name in ("__MACOSX",):
            continue

        dst = dst_root / item.name
        if item.is_dir():
            log(log_path, f"copy dir: {item} -> {dst}")
            copy_dir_merge(item, dst, log_path)
        else:
            log(log_path, f"copy file: {item} -> {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".new")
            shutil.copy2(item, tmp)
            replace_path(tmp, dst)


def copy_dir_merge(src: Path, dst: Path, log_path: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            copy_dir_merge(item, target, log_path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".new")
            shutil.copy2(item, tmp)
            replace_path(tmp, target)


def replace_path(tmp: Path, dst: Path) -> None:
    for attempt in range(20):
        try:
            if dst.exists():
                try:
                    dst.unlink()
                except Exception:
                    pass
            tmp.replace(dst)
            return
        except PermissionError:
            time.sleep(0.4)

    tmp.replace(dst)


def launch_app(root: Path, exe_name: str, log_path: Path) -> None:
    exe = root / exe_name
    if not exe.exists():
        log(log_path, f"exe not found: {exe}")
        return

    log(log_path, f"launch: {exe}")

    subprocess.Popen(
        [str(exe)],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def is_inside(root: Path, target: Path) -> bool:
    root = root.resolve()
    target = target.resolve()
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def log(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] "))
            f.write(str(text))
            f.write("\n")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
