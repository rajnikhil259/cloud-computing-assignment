# Task 5 — Subnetting 10.20.0.0/16

## Method

1. Sort the requirements from the largest to the smallest: app (1,000) → public (250) → data (100) → management (20).
2. For each subnet pick the smallest prefix whose usable host count `2^(32-prefix) - 2` is at least the requirement,
   i.e. the smallest `h` host bits with `2^h - 2 >= hosts`, prefix = 32 - h.
3. Place each subnet at the first address after the previous subnet's broadcast address, starting at 10.20.0.0.
   Because the blocks are allocated largest first, every block starts on a multiple of its own size, so each
   network address is valid (aligned) without leaving gaps.

| Requirement | Host bits `h` | Check `2^h - 2` | Prefix |
|---|---|---|---|
| app: 1,000 | 10 | 2^10 - 2 = 1,022 ≥ 1,000 (2^9 - 2 = 510 is too small) | /22 |
| public: 250 | 8 | 2^8 - 2 = 254 ≥ 250 (2^7 - 2 = 126 is too small) | /24 |
| data: 100 | 7 | 2^7 - 2 = 126 ≥ 100 (2^6 - 2 = 62 is too small) | /25 |
| management: 20 | 5 | 2^5 - 2 = 30 ≥ 20 (2^4 - 2 = 14 is too small) | /27 |

Working, block by block (a /22 spans 4 values of the third octet, a /24 one, a /25 half of one, a /27 32 addresses):

* app: starts at 10.20.0.0; size 1,024 = 4 × 256 → last address 10.20.3.255. Next free: 10.20.4.0.
* public: starts at 10.20.4.0; size 256 → last address 10.20.4.255. Next free: 10.20.5.0.
* data: starts at 10.20.5.0; size 128 → last address 10.20.5.127. Next free: 10.20.5.128.
* management: starts at 10.20.5.128; size 32 → last address 10.20.5.159. Next free: 10.20.5.160.

## Result

| Subnet | Network address | Prefix | Usable host range | Broadcast address | Usable hosts |
|---|---|---|---|---|---|
| app | 10.20.0.0 | /22 (255.255.252.0) | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 (255.255.255.0) | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 (255.255.255.128) | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 (255.255.255.224) | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

Addresses 10.20.5.160 – 10.20.255.255 remain free for future subnets.
The table is re-computed and checked by `tests/test_network.py` (Python `ipaddress`).

## NACL for the public subnet (`network/nacl.json`)

| Direction | Rule | Protocol | Ports | CIDR | Action | Purpose |
|---|---|---|---|---|---|---|
| inbound | 100 | all | all | 198.51.100.0/24 | deny | abusive range, blocked even on web ports |
| inbound | 110 | tcp | 80 | 0.0.0.0/0 | allow | HTTP from anywhere |
| inbound | 120 | tcp | 443 | 0.0.0.0/0 | allow | HTTPS from anywhere |
| inbound | 130 | tcp | 22 | 10.20.5.128/27 | allow | SSH only from management |
| inbound | 140 | tcp | 1024–65535 | 10.20.0.0/22 | allow | replies from the app subnet to the load balancer's ephemeral ports |
| inbound | 32766 | all | all | 0.0.0.0/0 | deny | explicit default deny |
| outbound | 100 | tcp | 8000 | 10.20.0.0/22 | allow | load balancer → app service |
| outbound | 110 | tcp | 1024–65535 | 0.0.0.0/0 | allow | replies to clients' ephemeral ports |
| outbound | 32766 | all | all | 0.0.0.0/0 | deny | explicit default deny |

Check: `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check`
(output in `results/task5/nacl_sample_check.txt`; an additional 24-packet edge-case set is in
`network/packets_extra.jsonl` with its output in `results/task5/nacl_extra_check.txt`).

**Why replies need their own rules.** A NACL is stateless: it does not remember that a packet belongs to a
connection it already allowed, so every packet — including the reply — is checked against the rules on its own.
A client's request to port 443 is allowed by inbound rule 120, but the response leaves towards the client's
ephemeral port (1024–65535), so it needs outbound rule 110; likewise the app's responses to the load balancer
arrive on the load balancer's ephemeral ports and need inbound rule 140. (A stateful security group would allow
those replies automatically.)

**Why the order matters for 198.51.100.0/24.** Rules are checked from the lowest number up and the first match
wins. A packet from 198.51.100.9 to port 443 matches both the deny for 198.51.100.0/24 and the allow for 443 from
0.0.0.0/0; the deny only takes effect because its number (100) is lower than the allow it must override (120).
Numbered after the allows, it would never be reached for web traffic.
