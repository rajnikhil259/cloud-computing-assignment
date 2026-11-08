"""Unit tests for the sharding and prompt logic of worker/worker.py."""
import os

import pytest

import worker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_shards_partition_the_input_without_gaps_or_repeats():
    records = [{"id": f"C{i:04d}"} for i in range(1, 3001)]
    for count in (1, 2, 3, 4, 6):
        parts = [worker.select_shard(records, i, count) for i in range(count)]
        ids = [r["id"] for p in parts for r in p]
        assert sorted(ids) == [r["id"] for r in records]          # every id exactly once
        assert len(set(ids)) == len(ids)


def test_shard_uses_line_number_modulo_count():
    records = [{"id": n} for n in range(10)]
    assert [r["id"] for r in worker.select_shard(records, 1, 3)] == [1, 4, 7]
    with pytest.raises(ValueError):
        worker.select_shard(records, 3, 3)


def test_prompt_file_has_placeholder_and_schema_terms():
    with open(os.path.join(ROOT, "prompts/teacher_prompt.txt"), encoding="utf-8") as f:
        template = f.read()
    prompt = worker.build_prompt(template, "set an alarm for six am")
    assert "{command}" not in prompt and "Command: set an alarm for six am" in prompt
    for word in ("intent", "date", "time", "place", "alarm_set", "recommendation_events"):
        assert word in template


def test_teacher_settings_are_fixed():
    assert worker.TEACHER_OPTIONS["temperature"] == 0 and worker.TEACHER_OPTIONS["seed"] == 42
    assert "\n" in worker.TEACHER_OPTIONS["stop"]          # one JSON line, no trailing notes
