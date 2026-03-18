"""Tests for scripts/validate_fbx.py."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest
from click.testing import CliRunner

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.validate_fbx import (
    validate_fbx_file,
    FBXValidationError,
    FBX_BINARY_MAGIC,
    main,
)


class TestValidateFBXFile:
    def test_nonexistent_file_raises(self, tmp_path: Path):
        with pytest.raises(FBXValidationError, match="File not found"):
            validate_fbx_file(tmp_path / "missing.fbx")

    def test_empty_file_raises(self, tmp_path: Path):
        f = tmp_path / "empty.fbx"
        f.write_bytes(b"")
        with pytest.raises(FBXValidationError, match="File is empty"):
            validate_fbx_file(f)

    def test_oversized_file_raises(self, tmp_path: Path):
        f = tmp_path / "big.fbx"
        # Create a file just over 1MB with max_size_mb=0.001
        f.write_bytes(b"x" * 2048)
        with pytest.raises(FBXValidationError, match="File too large"):
            validate_fbx_file(f, max_size_mb=0.001)

    def test_valid_binary_fbx(self, tmp_path: Path):
        f = tmp_path / "valid.fbx"
        # Write binary FBX magic + version 7400 + padding
        header = FBX_BINARY_MAGIC + b"\x00\x00" + struct.pack("<I", 7400)
        f.write_bytes(header + b"\x00" * 100)
        result = validate_fbx_file(f)
        assert result["format"] == "binary"
        assert result["valid"] is True

    def test_ascii_fbx_warns(self, tmp_path: Path):
        f = tmp_path / "ascii.fbx"
        f.write_bytes(b"; FBX 7.4.0 project file\nFBXHeaderExtension: {\n}")
        result = validate_fbx_file(f)
        assert result["format"] == "ascii"
        assert any("ASCII FBX" in w for w in result["warnings"])

    def test_unrecognized_header_warns(self, tmp_path: Path):
        f = tmp_path / "unknown.fbx"
        f.write_bytes(b"NOT_AN_FBX_FILE_AT_ALL")
        result = validate_fbx_file(f)
        assert any("recognized FBX header" in w for w in result["warnings"])

    def test_under_size_limit_passes(self, tmp_path: Path):
        f = tmp_path / "small.fbx"
        f.write_bytes(b"x" * 1000)
        result = validate_fbx_file(f, max_size_mb=20)
        assert result["valid"] is True
        assert result["file_size"] == 1000


class TestValidateFBXCLI:
    def test_cli_valid_file(self, tmp_path: Path):
        f = tmp_path / "ok.fbx"
        f.write_bytes(FBX_BINARY_MAGIC + b"\x00\x00" + struct.pack("<I", 7400) + b"\x00" * 100)
        runner = CliRunner()
        result = runner.invoke(main, [str(f)])
        assert result.exit_code == 0
        assert "Validation passed" in result.output

    def test_cli_missing_file(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(main, [str(tmp_path / "nope.fbx")])
        assert result.exit_code == 1

    def test_cli_json_output(self, tmp_path: Path):
        f = tmp_path / "ok.fbx"
        f.write_bytes(b"some data here")
        runner = CliRunner()
        result = runner.invoke(main, [str(f), "--json"])
        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert data["valid"] is True
