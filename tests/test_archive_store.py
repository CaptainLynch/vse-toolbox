from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.archive_store import (
    ArchiveCapacityError,
    ArchiveSafetyError,
    ArchiveStore,
    RetentionItem,
)


def store(tmp_path: Path, **kwargs) -> ArchiveStore:
    return ArchiveStore({"root": tmp_path}, reserve_bytes=0, **kwargs)


def archive(
    s: ArchiveStore,
    payload: bytes = b"abc",
    name: str = "report.xlsx",
    output_subdir: str = "",
):
    return s.write_stream(
        io.BytesIO(payload),
        source="tdc",
        report="sor",
        run_id="run-1",
        file_name=name,
        artifact_type="xlsx",
        root_id="root",
        expected_size=len(payload),
        chunk_size=1,
        output_subdir=output_subdir,
    )


def test_stream_layout_hash_and_collision_do_not_overwrite(tmp_path: Path):
    s = store(tmp_path)
    first = archive(s, b"abc")
    second = archive(s, b"xyz")
    assert first.relative_path.startswith("tdc/sor/")
    assert "/run-1/" in first.relative_path
    assert first.sha256 == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert first.relative_path != second.relative_path
    assert (tmp_path / first.relative_path).read_bytes() == b"abc"
    assert (tmp_path / second.relative_path).read_bytes() == b"xyz"


@pytest.mark.parametrize("component", ["..", "C:/escape", "CON", "bad\x00name"])
def test_rejects_unsafe_components(tmp_path: Path, component: str):
    s = store(tmp_path)
    with pytest.raises(ArchiveSafetyError):
        s.run_directory(component, "sor", "run", root_id="root")


def test_rejects_symlink_ancestor(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted")
    s = store(tmp_path)
    with pytest.raises(ArchiveSafetyError):
        s.run_directory("linked", "sor", "run", root_id="root")


def test_valid_nested_output_subdir(tmp_path: Path):
    s = store(tmp_path)
    subdir = "custom/nested/path"
    run_dir = s.run_directory("tdc", "sor", "run-1", root_id="root", output_subdir=subdir)
    assert run_dir.is_relative_to(tmp_path / "custom" / "nested" / "path")
    art = archive(s, b"payload data", name="data.xlsx", output_subdir=subdir)
    assert art.relative_path.startswith("custom/nested/path/tdc/sor/")
    assert (tmp_path / art.relative_path).read_bytes() == b"payload data"


@pytest.mark.parametrize(
    "bad_subdir",
    [
        # traversal
        "..",
        "../escape",
        "sub/..",
        "a/../b",
        "a/..",
        # absolute / drive / backslash
        "/absolute",
        "\\unc",
        "C:/drive",
        "C:\\drive",
        "a\\b",
        "d:path",
        ":bad",
        # empty segments / surrounding whitespace
        "a//b",
        "/a",
        "a/",
        "   ",
        " sub",
        "sub ",
        # Windows device names
        "CON",
        "con",
        "NUL/sub",
        "sub/AUX",
        "COM1",
        "sub/LPT1.log",
        "prn",
        "com9",
        # trailing dot or space in segments
        "sub.",
        "sub. ",
        "sub /nested",
        "sub./nested",
        "nested/part. ",
    ],
)
def test_rejects_invalid_output_subdir(tmp_path: Path, bad_subdir: str):
    s = store(tmp_path)
    with pytest.raises(ArchiveSafetyError):
        s.run_directory("tdc", "sor", "run-1", root_id="root", output_subdir=bad_subdir)


def test_rejects_reparse_escape_in_output_subdir(tmp_path: Path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-subdir"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "reparse_sub"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted")
    s = store(tmp_path)
    with pytest.raises(ArchiveSafetyError):
        s.run_directory("tdc", "sor", "run-1", root_id="root", output_subdir="reparse_sub")


def test_limit_failure_removes_partial_file(tmp_path: Path):
    s = store(tmp_path, max_bytes=2)
    with pytest.raises(ArchiveCapacityError):
        archive(s, b"abc")
    assert not list(tmp_path.rglob(".partial-*"))


def test_csv_formula_control_and_json_utf8(tmp_path: Path):
    s = store(tmp_path)
    csv_artifact = s.write_csv(
        [{"value": "  =1+1"}],
        ["value"],
        source="tdc",
        report="sor",
        run_id="2",
        file_name="rows.csv",
        artifact_type="csv",
        root_id="root",
    )
    assert "'  =1+1" in (tmp_path / csv_artifact.relative_path).read_text(encoding="utf-8-sig")
    with pytest.raises(ArchiveSafetyError):
        s.write_csv(
            [{"value": "bad\x00"}],
            ["value"],
            source="tdc",
            report="sor",
            run_id="3",
            file_name="bad.csv",
            artifact_type="csv",
            root_id="root",
        )
    json_artifact = s.write_json(
        {"名称": "数模"},
        source="tdc",
        report="data-model",
        run_id="4",
        file_name="snapshot.json",
        artifact_type="json",
        root_id="root",
    )
    assert json.loads((tmp_path / json_artifact.relative_path).read_text(encoding="utf-8")) == {"名称": "数模"}


def test_retention_plan_then_explicit_confined_delete(tmp_path: Path):
    s = store(tmp_path)
    artifact = archive(s)
    target = tmp_path / artifact.relative_path
    old = (datetime.now(timezone.utc) - timedelta(days=100)).timestamp()
    os.utime(target, (old, old))
    plan = s.plan_retention(root_id="root", retention_days=90)
    assert [item.relative_path for item in plan] == [artifact.relative_path]
    assert target.exists()
    assert s.execute_retention(plan, root_id="root") == (artifact.relative_path,)
    assert not target.exists()
    with pytest.raises(ArchiveSafetyError):
        s.execute_retention([RetentionItem("../outside", 1, "")], root_id="root")
