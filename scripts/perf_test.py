import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "perf@example.com"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "Test-password-123"
USERS = 50
ROUNDS = 10
PAGES = ["/", "/login", "/dashboard", "/parking", "/my-reservations"]
P90_LIMIT = 2.0
VERIFY = False


def csrf(html):
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html) or re.search(
        r'value="([^"]+)"[^>]*name="csrf_token"', html
    )
    return m.group(1) if m else None


def make_session(_):
    s = requests.Session()
    s.verify = VERIFY
    page = s.get(BASE + "/login", timeout=30).text
    data = {"email": EMAIL, "password": PASSWORD}
    token = csrf(page)
    if token:
        data["csrf_token"] = token
    r = s.post(BASE + "/login", data=data, timeout=30, allow_redirects=False)
    return s, r.status_code in (302, 303)


def run_user(s):
    times, errors = [], 0
    for i in range(ROUNDS):
        for path in PAGES:
            t = time.perf_counter()
            try:
                r = s.get(BASE + path, timeout=30)
                if r.status_code >= 400:
                    errors += 1
            except requests.RequestException:
                errors += 1
            times.append(time.perf_counter() - t)
    return times, errors


def main():
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        sessions = list(ex.map(make_session, range(USERS)))
    ok = sum(1 for _, good in sessions if good)
    print(f"logged in: {ok}/{USERS}")
    if ok == 0:
        print("FAIL: login did not work; check credentials and CSRF")
        sys.exit(1)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=USERS) as ex:
        results = list(ex.map(run_user, [s for s, good in sessions if good]))
    wall = time.perf_counter() - start

    times = sorted(t for ts, _ in results for t in ts)
    errors = sum(e for _, e in results)
    p90 = times[int(len(times) * 0.9) - 1]
    print(f"concurrent users: {ok}")
    print(f"requests: {len(times)}  errors: {errors}  wall: {wall:.1f}s")
    print(f"mean: {statistics.mean(times):.3f}s  median: {statistics.median(times):.3f}s")
    print(f"p90: {p90:.3f}s  max: {times[-1]:.3f}s  (limit {P90_LIMIT}s)")
    passed = p90 <= P90_LIMIT and errors == 0
    print("RESULT: PASS" if passed else "RESULT: FAIL")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
