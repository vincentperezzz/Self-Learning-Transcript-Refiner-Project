import json, sys

fname = sys.argv[1] if len(sys.argv) > 1 else r"d:\dev\Self-Learning-Transcript-Refiner-Project\test_output.json"
with open(fname) as f:
    d = json.load(f)

for s in d["segments"]:
    corr = len(s["corrections"])
    mode = s["anchor_mode"]
    orig = s["original_text"][:100]
    if corr > 0:
        ref = s["refined_text"][:100]
        print(f"[{mode:12s}] {corr} fix | ORIG: {orig}")
        print(f"              -> REF : {ref}")
        for c in s["corrections"]:
            print(f'                * {c["source"]}: "{c["original"]}" -> "{c["corrected"]}"')
    else:
        print(f"[{mode:12s}]  ok  | {orig}")

print(f"\nTotal corrections: {d['total_corrections']}")
print(f"Total segments: {len(d['segments'])}")
