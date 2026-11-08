"""Checks the subnet plan and the NACL against the sample packets and extra edge cases."""
import ipaddress
import json
import math
import os

import nacl_sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plan():
    cur = int(ipaddress.ip_address("10.20.0.0"))
    out = {}
    for name, hosts in [("app", 1000), ("public", 250), ("data", 100), ("management", 20)]:
        prefix = 32 - math.ceil(math.log2(hosts + 2))
        net = ipaddress.ip_network((cur, prefix))
        out[name] = net
        cur = int(net.broadcast_address) + 1
    return out


def test_subnet_table_matches_document():
    p = plan()
    assert [str(n) for n in p.values()] == ["10.20.0.0/22", "10.20.4.0/24", "10.20.5.0/25", "10.20.5.128/27"]
    with open(os.path.join(ROOT, "network/subnets.md"), encoding="utf-8") as f:
        doc = f.read()
    for net in p.values():
        assert str(net.network_address) in doc and str(net.broadcast_address) in doc
        assert f"{net.network_address + 1} – {net.broadcast_address - 1}" in doc
        assert f"{net.num_addresses - 2:,}" in doc


def test_nacl_decides_every_packet_as_expected():
    rules = nacl_sim.load_rules(os.path.join(ROOT, "network/nacl.json"))
    for fname in ("packets_sample.jsonl", "packets_extra.jsonl"):
        with open(os.path.join(ROOT, "network", fname), encoding="utf-8") as f:
            for line in f:
                p = json.loads(line)
                assert nacl_sim.decide(rules, p)[0] == p["expected"], p["id"]


def test_abusive_range_deny_comes_before_web_allows():
    rules = nacl_sim.load_rules(os.path.join(ROOT, "network/nacl.json"))["inbound"]
    deny = next(r for r in rules if r["cidr"] == "198.51.100.0/24")
    allows = [r for r in rules if r["action"] == "allow" and r["cidr"] == "0.0.0.0/0"]
    assert deny["action"] == "deny" and all(deny["rule"] < r["rule"] for r in allows)
