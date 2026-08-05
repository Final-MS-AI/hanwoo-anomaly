import shutil
import sys
from datetime import datetime
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"already applied: {path.name}")
        return
    if old not in text:
        raise RuntimeError(f"target code not found: {path} / {old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"updated: {path.name}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python3 install_family_sharing.py /home/azureuser/3rd_fastapi")

    source_dir = Path(__file__).resolve().parent
    backend_dir = Path(sys.argv[1]).resolve()
    required = [
        backend_dir / "main.py",
        backend_dir / "device_api.py",
        backend_dir / "device_claim_api.py",
        backend_dir / "device_disconnect_api.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("required files missing: " + ", ".join(missing))

    backup_dir = backend_dir / ("family-sharing-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup_dir.mkdir()
    for path in required:
        shutil.copy2(path, backup_dir / path.name)
    print(f"backup: {backup_dir}")

    shutil.copy2(source_dir / "family_device_api.py", backend_dir / "family_device_api.py")
    print("copied: family_device_api.py")

    replace_once(
        backend_dir / "device_claim_api.py",
        '@router.get("/devices/mine")',
        '@router.get("/devices/mine-legacy")',
    )
    replace_once(
        backend_dir / "device_disconnect_api.py",
        '"/devices/connection",',
        '"/devices/connection-legacy",',
    )
    replace_once(
        backend_dir / "device_api.py",
        '@router.post("/actuators")',
        '@router.post("/actuators-legacy")',
    )
    replace_once(
        backend_dir / "device_api.py",
        '@router.get("/devices/{device_id}/state")',
        '@router.get("/devices/{device_id}/state-legacy")',
    )

    main_path = backend_dir / "main.py"
    text = main_path.read_text(encoding="utf-8")
    import_line = "from family_device_api import router as family_device_router"
    include_line = "app.include_router(family_device_router)"
    if import_line not in text:
        text = import_line + "\n" + text
    if include_line not in text:
        cors_marker = "app.add_middleware("
        include_at = text.find(cors_marker)
        if include_at < 0:
            raise RuntimeError("app.add_middleware(...) not found in main.py")
        text = text[:include_at] + include_line + "\n\n" + text[include_at:]
    main_path.write_text(text, encoding="utf-8")
    print("registered router: main.py")


if __name__ == "__main__":
    main()
