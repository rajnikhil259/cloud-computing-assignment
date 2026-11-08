"""Unit tests for worker/clean.py: the five removal rules, id order and the count identity."""
import hashlib
import json

import clean


def rec(i, text, raw):
    return {"id": f"C{i:04d}", "text": text, "teacher_raw": raw}


GOOD = '{"intent": "alarm_set", "date": "tomorrow", "time": "seven am", "place": null}'


def test_each_rule_and_identity():
    rows = [
        rec(5, "set an alarm for seven am tomorrow", GOOD),                       # kept
        rec(1, "what time is it", "It is a datetime query."),                    # (a) not JSON
        rec(2, "what time is it in rome", '{"intent": "datetime_query", "place": "rome"}'),  # (b) keys
        rec(3, "play some jazz", '{"intent": "play_music", "date": null, "time": null, "place": null}'),  # (c)
        rec(4, "weather in paris", '{"intent": "weather_query", "date": null, "time": null, "place": "london"}'),  # (d)
        rec(6, "set an alarm for seven am tomorrow", GOOD),                       # (e) duplicate of C0005
        rec(7, "  Set an alarm for seven am   tomorrow ", GOOD),                  # (e) same text after normalising
    ]
    kept, rejected, counts = clean.clean(rows)
    assert [r["id"] for r in kept] == ["C0005"]
    assert {r["id"]: r["reason"] for r in rejected} == {
        "C0001": "a_invalid_json", "C0002": "b_wrong_keys", "C0003": "c_bad_intent",
        "C0004": "d_bad_slot", "C0006": "e_duplicate", "C0007": "e_duplicate"}
    assert counts["input_records"] == 7 and counts["kept"] == 1 and counts["identity_holds"]


def test_slot_rules():
    text = "Wake me up at Seven AM on friday"
    ok = '{"intent": "alarm_set", "date": "friday", "time": "seven am", "place": null}'
    assert clean.check_reply(text, ok)[0] is None                      # case-insensitive copy is fine
    assert clean.check_reply(text, ok.replace('"seven am"', '"07:00"'))[0] == "d_bad_slot"   # converted value
    assert clean.check_reply(text, ok.replace('"friday"', '""'))[0] == "d_bad_slot"         # empty string
    assert clean.check_reply(text, ok.replace('"friday"', "5"))[0] == "d_bad_slot"          # not text
    assert clean.check_reply(text, "[1, 2]")[0] == "b_wrong_keys"                          # JSON but not an object
    assert clean.check_reply(text, ok.replace("}", ', "extra": null}'))[0] == "b_wrong_keys"
    assert clean.check_reply(text, '```json\n' + ok + '\n```')[0] == "a_invalid_json"


def test_output_is_deterministic_and_in_id_order():
    def reply(intent, place="null"):
        return '{"intent": "%s", "date": null, "time": null, "place": %s}' % (intent, place)

    shards = {
        "shard-1.jsonl": [rec(2, "is it raining in oslo", reply("weather_query", '"oslo"'))],
        "shard-0.jsonl": [rec(1, "delete my meeting", reply("calendar_remove")),
                          rec(10, "what is the date", reply("datetime_query"))],
    }
    train1, sha1, report, _ = clean.build_outputs(shards, ["C0001", "C0002", "C0010"])
    train2, sha2, _, _ = clean.build_outputs(dict(reversed(list(shards.items()))), ["C0001", "C0002", "C0010"])
    assert train1 == train2 and sha1 == sha2
    assert [json.loads(line)["id"] for line in train1.splitlines()] == ["C0001", "C0002", "C0010"]
    assert sha1 == hashlib.sha256(train1.encode()).hexdigest() + "  train.jsonl\n"
    assert report["coverage"]["ok"]
    first = json.loads(train1.splitlines()[0])
    assert first["teacher_json"] == '{"intent": "calendar_remove", "date": null, "time": null, "place": null}'


def test_coverage_detects_gaps_and_repeats():
    shards = {"shard-0.jsonl": [rec(1, "a", GOOD)], "shard-1.jsonl": [rec(1, "a", GOOD)]}
    cov = clean.coverage(shards, ["C0001", "C0002"])
    assert cov["repeated_ids"] == ["C0001"] and cov["missing_ids"] == ["C0002"] and not cov["ok"]
