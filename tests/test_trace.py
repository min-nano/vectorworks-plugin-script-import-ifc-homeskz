"""クラッシュ診断用トレース (tracing.py) のテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from vectorworks_plugin_import_ifc_homeskz import tracing as trace_mod


def test_trace_writes_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trace_mod, 'TRACE_ENABLED', True)
    log = tmp_path / 'trace.log'
    monkeypatch.setattr(trace_mod, 'TRACE_PATH', str(log))

    trace_mod.trace('hello trace')

    content = log.read_text(encoding='utf-8')
    assert 'hello trace' in content
    # タイムスタンプ付きの 1 行として追記される。
    assert content.endswith('hello trace\n')


def test_trace_appends_multiple_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trace_mod, 'TRACE_ENABLED', True)
    log = tmp_path / 'trace.log'
    monkeypatch.setattr(trace_mod, 'TRACE_PATH', str(log))

    trace_mod.trace('first')
    trace_mod.trace('second')

    lines = log.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    assert 'first' in lines[0]
    assert 'second' in lines[1]


def test_trace_disabled_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(trace_mod, 'TRACE_ENABLED', False)
    log = tmp_path / 'trace.log'
    monkeypatch.setattr(trace_mod, 'TRACE_PATH', str(log))

    trace_mod.trace('hello')

    assert not log.exists()


def test_trace_swallows_write_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # 書き込み先が存在しなくても例外を漏らさない(インポート処理を妨げない)。
    monkeypatch.setattr(trace_mod, 'TRACE_ENABLED', True)
    monkeypatch.setattr(
        trace_mod, 'TRACE_PATH', '/nonexistent_dir_for_trace_test/trace.log')

    trace_mod.trace('hello')  # 例外にならないこと
