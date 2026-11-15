import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XML = ROOT / "test-results" / "junit.xml"
OUT = ROOT / "docs" / "RTM_STATUS.md"

RTM = [
    ("PVT-F-001", "TC-Auth-01"), ("PVT-F-002", "TC-Auth-02"), ("PVT-F-003", "TC-Auth-03"),
    ("PVT-F-004", "TC-Slot-01"), ("PVT-F-005", "TC-Slot-02"), ("PVT-F-006", "TC-Slot-03"),
    ("PVT-F-007", "TC-Slot-04"), ("PVT-F-008", "TC-Track-01"), ("PVT-F-009", "TC-Track-02"),
    ("PVT-F-010", "TC-Track-03"), ("PVT-F-011", "TC-Track-04"), ("PVT-F-012", "TC-Bill-01"),
    ("PVT-F-013", "TC-Bill-02"), ("PVT-F-014", "TC-Pay-01"), ("PVT-F-015", "TC-Admin-01"),
    ("PVT-F-016", "TC-Admin-02"), ("PVT-F-017", "TC-Admin-03"), ("PVT-NF-001", "TC-Perf-01"),
    ("PVT-NF-002", "TC-Perf-02"), ("PVT-NF-004", "TC-UX-01"), ("PVT-NF-005", "TC-Sec-01"),
    ("PRJ-SR-001", "TC-Sec-01"), ("PRJ-SR-002", "TC-Sec-02"), ("PRJ-SR-003", "TC-Sec-03"),
    ("PRJ-SR-004", "TC-Sec-04"), ("PRJ-SR-005", "TC-Sec-05"),
]
EVIDENCE = {
    "TC-Perf-01": ROOT / "docs" / "perf_results.txt",
    "TC-Perf-02": ROOT / "docs" / "perf_results.txt",
    "TC-Sec-03": ROOT / "docs" / "tls_evidence.txt",
}
MANUAL = {"TC-UX-01": "Manual (desktop/mobile check)"}


def run_pytest():
    XML.parent.mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", f"--junitxml={XML}"], cwd=ROOT, check=False
    )


def collect():
    found = {}
    for case in ET.parse(XML).getroot().iter("testcase"):
        m = re.match(r"test_tc_([a-z]+)_(\d+)", case.get("name", ""))
        if not m:
            continue
        tc = f"TC-{m.group(1).capitalize()}-{m.group(2)}"
        failed = case.find("failure") is not None or case.find("error") is not None
        found.setdefault(tc, []).append(not failed)
    return found


def status(tc, found):
    if tc in found:
        return ("Pass" if all(found[tc]) else "Fail"), f"{len(found[tc])} automated test(s)"
    path = EVIDENCE.get(tc)
    if path and path.exists():
        return ("Pass" if "RESULT: PASS" in path.read_text() else "Fail"), f"Evidence: {path.name}"
    if tc in MANUAL:
        return "Manual", MANUAL[tc]
    return "Not run", "No automated test or evidence yet"


def main():
    run_pytest()
    found = collect()
    rows = []
    for req, tc in RTM:
        s, note = status(tc, found)
        rows.append(f"| {req} | {tc} | {s} | {note} |")
    passed = sum(r.split("|")[3].strip() == "Pass" for r in rows)
    text = [
        "# RTM Status",
        "",
        f"Generated on {date.today().isoformat()} by `scripts/generate_rtm.py`.",
        "",
        f"**{passed} of {len(rows)} requirement rows currently pass.**",
        "",
        "| Requirement | Test Case | Status | Evidence |",
        "|---|---|---|---|",
        *rows,
        "",
    ]
    OUT.write_text("\n".join(text))
    print(f"wrote {OUT}")
    print("\n".join(rows))


main()
