#!/usr/bin/env python3
"""
Finds the cheapest GPU offer whose machine also currently offers volume
storage. GPU-first, volume-second — GPU availability is the scarce,
fast-moving resource; volume-offering hosts and GPU-available-right-now
hosts are largely separate populations (proven empirically: a volume-
first search once picked 10/10 machines with zero free GPUs).

Reads two files written by the calling shell script (avoids ever
embedding Python logic directly inside a YAML run: block again):
  /tmp/gpu_offers.json  — output of `vastai search offers ... --raw`
  /tmp/vol_offers.json  — output of `vastai search volumes ... --raw`

Prints one line of JSON to stdout: {"gpu_offer_id", "machine_id", "vol_offer_id"}
or an empty string if no match exists. Exit code 1 if no match found.
"""
import json
import sys

with open("/tmp/gpu_offers.json") as f:
    gpu_offers = json.load(f)
with open("/tmp/vol_offers.json") as f:
    vol_offers = json.load(f)

vol_by_machine = {}
for v in vol_offers:
    vol_by_machine.setdefault(v["machine_id"], v)

match = None
for g in gpu_offers:
    machine_id = g["machine_id"]
    if machine_id in vol_by_machine:
        match = {
            "gpu_offer_id": g["id"],
            "machine_id": machine_id,
            "vol_offer_id": vol_by_machine[machine_id]["id"],
        }
        break

if match is None:
    print(f"Checked {len(gpu_offers)} GPU offers — none on a machine that also offers volume storage right now.", file=sys.stderr)
    sys.exit(1)

print(json.dumps(match))
