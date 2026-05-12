from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


CURRENT_APP_VERSION = "0.1.0"
EXE_NAME = "RQ_Calc.exe"

# Если репозиторий называется rq-calculator и ветка main:
UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/AlexGronskiy/rq-calculator/main/updates/latest.json"
)

LOCAL_STATE_FILE = "update_state.json"
UPDATE_CACHE_DIR = ".update_cache"

# Компоненты по умолчанию. Версии этих компонентов считаются установленными,
# если update_state.json ещё не создан.
DEFAULT_COMPONENT_VERSIONS = {
    "app": CURRENT_APP_VERSION,
    "resources": CURRENT_APP_VERSION,
    "database": CURRENT_APP_VERSION,
}

# Куда ставить компоненты, если target/kind не указаны в latest.json.
DEFAULT_COMPONENT_META = {
    "app": {"kind": "zip", "target": "."},
    "resources": {"kind": "zip", "target": "."},
    "database": {"kind": "file", "target": "rqdata.sqlite"},
}


ProgressCallback = Optional[Callable[[str], None]]


@dataclass(frozen=True)
class UpdateComponent:
    name: str
    version: str
    url: str
    sha256: str
    kind: str
    target: str
    restart_required: bool
    notes: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    update_available: bool
    current_version: str
    remote_version: str
    notes: str
    components_to_update: List[UpdateComponent]
    manifest: Dict[str, Any]
    error: str = ""


class UpdateManager:
    def __init__(
        self,
        *,
        manifest_url: str = UPDATE_MANIFEST_URL,
        exe_name: str = EXE_NAME,
        current_version: str = CURRENT_APP_VERSION,
        root_dir: Optional[Path] = None,
    ):
        self.manifest_url = str(manifest_url or UPDATE_MANIFEST_URL)
        self.exe_name = str(exe_name or EXE_NAME)
        self.current_version = str(current_version or CURRENT_APP_VERSION)
        self.root_dir = Path(root_dir) if root_dir is not None else self.detect_root_dir()

    @staticmethod
    def detect_root_dir() -> Path:
        candidates: List[Path] = []

        try:
            if getattr(sys, "frozen", False):
                candidates.append(Path(sys.executable).resolve().parent)
        except Exception:
            pass

        try:
            candidates.append(Path.cwd().resolve())
        except Exception:
            pass

        try:
            here = Path(__file__).resolve()
            candidates.append(here.parents[2])
            candidates.append(here.parents[3])
        except Exception:
            pass

        for c in candidates:
            try:
                if (c / "resources").exists() or (c / "rqdata.sqlite").exists():
                    return c
            except Exception:
                pass

        return Path.cwd().resolve()

    @property
    def state_path(self) -> Path:
        return self.root_dir / LOCAL_STATE_FILE

    @property
    def cache_dir(self) -> Path:
        return self.root_dir / UPDATE_CACHE_DIR

    def check_for_updates(self, progress: ProgressCallback = None) -> UpdateCheckResult:
        try:
            if progress:
                progress("Получаю информацию об обновлениях...")

            manifest = self._download_json(self.manifest_url)
            local_state = self._load_local_state()

            remote_version = str(manifest.get("version") or "0.0.0")
            notes = str(manifest.get("notes") or "")

            components_raw = manifest.get("components") or {}
            if not isinstance(components_raw, dict):
                raise ValueError("В latest.json поле components должно быть объектом.")

            components_to_update: List[UpdateComponent] = []

            for name, raw in components_raw.items():
                if not isinstance(raw, dict):
                    continue

                comp_name = str(name or "").strip()
                if not comp_name:
                    continue

                remote_comp_version = str(raw.get("version") or remote_version or "0.0.0")
                local_comp_version = self._local_component_version(local_state, comp_name)

                if compare_versions(remote_comp_version, local_comp_version) <= 0:
                    continue

                default_meta = DEFAULT_COMPONENT_META.get(comp_name, {})
                url = str(raw.get("url") or "").strip()
                sha = str(raw.get("sha256") or "").strip().lower()

                if not url:
                    raise ValueError(f"У компонента {comp_name!r} не указан url.")
                if not sha:
                    raise ValueError(f"У компонента {comp_name!r} не указан sha256.")

                components_to_update.append(
                    UpdateComponent(
                        name=comp_name,
                        version=remote_comp_version,
                        url=url,
                        sha256=sha,
                        kind=str(raw.get("kind") or default_meta.get("kind") or "zip").strip().lower(),
                        target=str(raw.get("target") or default_meta.get("target") or ".").strip(),
                        restart_required=bool(raw.get("restart_required", True)),
                        notes=str(raw.get("notes") or ""),
                    )
                )

            return UpdateCheckResult(
                ok=True,
                update_available=bool(components_to_update),
                current_version=self.current_version,
                remote_version=remote_version,
                notes=notes,
                components_to_update=components_to_update,
                manifest=manifest,
            )

        except Exception as e:
            return UpdateCheckResult(
                ok=False,
                update_available=False,
                current_version=self.current_version,
                remote_version="0.0.0",
                notes="",
                components_to_update=[],
                manifest={},
                error=str(e),
            )

    def prepare_update(self, result: UpdateCheckResult, progress: ProgressCallback = None) -> Path:
        if not result.ok:
            raise RuntimeError(result.error or "Проверка обновлений завершилась ошибкой.")

        if not result.update_available:
            raise RuntimeError("Нет компонентов для обновления.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        downloads_dir = self.cache_dir / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        downloaded_components: List[Dict[str, Any]] = []

        for comp in result.components_to_update:
            if progress:
                progress(f"Скачиваю: {component_title(comp.name)}...")

            suffix = ".zip" if comp.kind == "zip" else Path(comp.target).suffix
            if not suffix:
                suffix = ".bin"

            dst = downloads_dir / f"{safe_filename(comp.name)}{suffix}"
            self._download_file(comp.url, dst)

            if progress:
                progress(f"Проверяю: {component_title(comp.name)}...")

            actual_sha = sha256_file(dst)
            if actual_sha.lower() != comp.sha256.lower():
                try:
                    dst.unlink(missing_ok=True)
                except Exception:
                    pass
                raise RuntimeError(
                    f"Хеш компонента {comp.name!r} не совпал.\n"
                    f"Ожидалось: {comp.sha256}\n"
                    f"Получено: {actual_sha}"
                )

            downloaded_components.append(
                {
                    "name": comp.name,
                    "version": comp.version,
                    "source": str(dst),
                    "kind": comp.kind,
                    "target": comp.target,
                    "restart_required": comp.restart_required,
                }
            )

        state_after = self._build_state_after(result)

        plan = {
            "root_dir": str(self.root_dir),
            "exe_name": self.exe_name,
            "pid": int(os.getpid()),
            "components": downloaded_components,
            "delete": list(result.manifest.get("delete") or []),
            "state_after": state_after,
        }

        plan_path = self.cache_dir / "update_plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan_path

    def launch_updater(self, plan_path: Path) -> None:
        plan_path = Path(plan_path)
        if not plan_path.exists():
            raise FileNotFoundError(f"План обновления не найден: {plan_path}")

        updater_cmd = self._build_updater_command(plan_path)

        subprocess.Popen(
            updater_cmd,
            cwd=str(self.root_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def _build_updater_command(self, plan_path: Path) -> List[str]:
        root = self.root_dir

        if sys.platform.startswith("win"):
            updater_exe = root / "updater.exe"
        else:
            updater_exe = root / "updater"

        if updater_exe.exists():
            return [str(updater_exe), "--plan", str(plan_path)]

        # dev-режим: updater.py лежит рядом с update_manager.py.
        updater_py = Path(__file__).resolve().with_name("updater.py")
        if updater_py.exists():
            return [sys.executable, str(updater_py), "--plan", str(plan_path)]

        raise FileNotFoundError(
            "Не найден updater.exe рядом с RQ_Calc.exe. "
            "Для релизной сборки updater.exe должен лежать в корне папки программы."
        )

    def _download_json(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RQ-Calculator-Updater",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("latest.json должен содержать JSON-объект.")
        return data

    def _download_file(self, url: str, dst: Path) -> None:
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "RQ-Calculator-Updater",
                "Accept": "application/octet-stream,*/*",
            },
        )

        tmp = dst.with_suffix(dst.suffix + ".part")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, tmp.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            tmp.replace(dst)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def _load_local_state(self) -> Dict[str, Any]:
        path = self.state_path
        if not path.exists():
            return {
                "version": self.current_version,
                "components": {
                    name: {"version": ver}
                    for name, ver in DEFAULT_COMPONENT_VERSIONS.items()
                },
            }

        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _local_component_version(self, state: Dict[str, Any], component_name: str) -> str:
        comps = state.get("components") if isinstance(state, dict) else None
        if isinstance(comps, dict):
            raw = comps.get(component_name)
            if isinstance(raw, dict):
                v = raw.get("version")
                if v is not None:
                    return str(v)
            elif raw is not None:
                return str(raw)

        return str(DEFAULT_COMPONENT_VERSIONS.get(component_name, "0.0.0"))

    def _build_state_after(self, result: UpdateCheckResult) -> Dict[str, Any]:
        current = self._load_local_state()
        comps = current.get("components") if isinstance(current, dict) else None
        if not isinstance(comps, dict):
            comps = {}

        for comp in result.components_to_update:
            comps[comp.name] = {"version": comp.version}

        return {
            "version": result.remote_version or self.current_version,
            "components": comps,
        }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_filename(value: str) -> str:
    out = []
    for ch in str(value or ""):
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("._") or "component"


def component_title(name: str) -> str:
    n = str(name or "").strip().lower()
    if n == "app":
        return "программа"
    if n == "resources":
        return "ресурсы"
    if n == "database":
        return "база данных"
    return name


def compare_versions(a: str, b: str) -> int:
    pa = _version_parts(a)
    pb = _version_parts(b)
    max_len = max(len(pa), len(pb), 1)
    pa += [0] * (max_len - len(pa))
    pb += [0] * (max_len - len(pb))

    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0


def _version_parts(v: str) -> List[int]:
    parts: List[int] = []
    cur = ""
    for ch in str(v or ""):
        if ch.isdigit():
            cur += ch
        else:
            if cur:
                parts.append(int(cur))
                cur = ""
    if cur:
        parts.append(int(cur))
    return parts or [0]
