#!/usr/bin/env python3
"""Сверка снимка физического ядра с эталоном.

Зачем это нужно. `attenuator_app/core/` — **снимок** ядра, оригинал живёт в
исследовательском репозитории `THz-Unified-Optimizer`. Правило рабочего
пространства: поток вещества односторонний, физика зреет там, сюда приезжает
застывший результат. Главный риск такой схемы — **тихое расхождение**: кто-то
правит формулу здесь, оригинал остаётся прежним, и два места считают
по-разному, не подавая признаков.

Скрипт закрывает этот риск двумя режимами:

    python tools/verify_core.py
        Сверяет core/ с зафиксированными хешами (tools/core_manifest.json).
        Работает без исследовательского репозитория — годится для CI и для
        машины, где его нет вовсе.

    python tools/verify_core.py --against "<путь к THz-Unified-Optimizer>"
        Сверяет core/ напрямую с оригиналом. Так проверяют, что снимок не
        отстал после правки физики в исследовательском репозитории.

    python tools/verify_core.py --update
        Перезаписывает манифест текущим состоянием. Вызывать ТОЛЬКО после
        осознанного обновления снимка из оригинала, иначе смысл сверки
        теряется: манифест начнёт подтверждать любое расхождение.

Выход: 0 — совпало, 1 — расхождение (и тогда печатается, что именно).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CORE = REPO / "attenuator_app" / "core"
MANIFEST = HERE / "core_manifest.json"

#: путь ядра внутри исследовательского репозитория
ORIGIN_REL = Path("attenuator_app") / "core"


def digest(path: Path) -> str:
    """SHA-256 файла, нормализованный по переводу строк.

    CRLF/LF намеренно приводится к LF: git на Windows раскладывает файлы с
    CRLF, и без нормализации сверка ловила бы не расхождение физики, а
    настройку рабочей копии. Ровно на этом уже спотыкался хук бюджета.
    """
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def snapshot(core_dir: Path) -> dict[str, str]:
    if not core_dir.is_dir():
        sys.exit(f"нет каталога ядра: {core_dir}")
    return {
        p.relative_to(core_dir).as_posix(): digest(p)
        for p in sorted(core_dir.rglob("*.py"))
        if "__pycache__" not in p.parts
    }


def compare(current: dict[str, str], reference: dict[str, str], ref_name: str) -> int:
    changed = sorted(k for k in current.keys() & reference.keys() if current[k] != reference[k])
    added = sorted(current.keys() - reference.keys())
    removed = sorted(reference.keys() - current.keys())

    if not (changed or added or removed):
        print(f"ядро совпадает с {ref_name}: {len(current)} файлов, расхождений нет")
        return 0

    print(f"РАСХОЖДЕНИЕ с {ref_name}:", file=sys.stderr)
    for k in changed:
        print(f"  изменён:  {k}", file=sys.stderr)
    for k in added:
        print(f"  лишний:   {k}  (есть здесь, нет в эталоне)", file=sys.stderr)
    for k in removed:
        print(f"  пропал:   {k}  (есть в эталоне, нет здесь)", file=sys.stderr)
    print(
        "\nЧто делать: правка физики делается в исследовательском репозитории, "
        "затем снимок обновляется целиком и манифест перевыпускается "
        "(--update). Править ядро здесь — значит завести вторую версию физики.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="сверка снимка ядра с эталоном")
    ap.add_argument("--against", metavar="PATH",
                    help="корень исследовательского репозитория для прямой сверки")
    ap.add_argument("--update", action="store_true",
                    help="перезаписать манифест текущим состоянием (осознанно!)")
    args = ap.parse_args()

    current = snapshot(CORE)

    if args.update:
        MANIFEST.write_text(
            json.dumps({"files": current, "n": len(current)}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        print(f"манифест перевыпущен: {len(current)} файлов -> {MANIFEST.name}")
        return 0

    if args.against:
        origin = Path(args.against).expanduser().resolve() / ORIGIN_REL
        return compare(current, snapshot(origin), f"оригиналом {origin}")

    if not MANIFEST.exists():
        sys.exit(f"нет манифеста {MANIFEST} — создайте его: verify_core.py --update")
    reference = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    return compare(current, reference, "манифестом")


if __name__ == "__main__":
    raise SystemExit(main())
