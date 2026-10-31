"""Tests for how a Build run decides what to make (release_plan.py) and for the Mac test build that sends nothing.
No game or screen needed.

Run from the project folder:  python tests/test_release.py
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["MAPLE_EXP_DATA"] = tempfile.mkdtemp()           # never touch your real data
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import release_plan as rp  # noqa: E402
import maple_exp as m  # noqa: E402

failures = 0


def check(name, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + name)
    failures += not ok


SOURCE = 'import os\r\nVERSION = "0.9.16-beta"\r\nWINDOW_TITLE = "x"\r\n'
RELEASED = 'export const RELEASED = [\n  "0.9.14-beta", "0.9.15-beta", "0.9.16-beta",\n];\n'


def planned(ref_type, name, source=SOURCE, released=RELEASED):
    try:
        return rp.plan(ref_type, name, source, released)
    except rp.PlanError as e:
        return str(e)


# ---- which kind of run a tag starts
check("a release tag that matches VERSION and is listed: a release (Windows + Macs, one draft)",
      planned("tag", "v0.9.16-beta") == {"kind": "release", "tag": "v0.9.16-beta", "version": "0.9.16-beta"})
check("a Mac test tag: a mactest run whose build calls itself 0.9.16-mactest.1",
      planned("tag", "mac-test-v0.9.16-beta.1") == {"kind": "mactest", "tag": "mac-test-v0.9.16-beta.1",
                                                     "version": "0.9.16-mactest.1"})
check("...the test number counts up", planned("tag", "mac-test-v0.9.16-beta.12")["version"] == "0.9.16-mactest.12")
check("...it doesn't need VERSION to match yet (the test download comes before the release's own version bump)",
      planned("tag", "mac-test-v0.9.16-beta.1", SOURCE.replace("0.9.16", "0.9.15"))["kind"] == "mactest")
check("a branch run (Run workflow): builds, keeps the files, makes no release; VERSION as it is",
      planned("branch", "mac-test-m04") == {"kind": "branch", "tag": "", "version": "0.9.16-beta"})
check("...even a branch whose name looks like a tag", planned("branch", "v9.9.9")["kind"] == "branch")

wrong = {
    "a release tag different from VERSION": planned("tag", "v0.9.17-beta"),
    "a release tag whose version isn't in released.js": planned("tag", "v0.9.16-beta", released=RELEASED.replace('"0.9.16-beta"', '"0.9.15-beta"')),
    "a release tag with the Mac test word in it": planned("tag", "v0.9.16-mactest.1"),
}
for what, answer in wrong.items():
    check(f"{what}: refused with a reason", isinstance(answer, str) and len(answer) > 20)
check("...the VERSION mismatch says both versions", "v0.9.17-beta" in wrong["a release tag different from VERSION"]
      and "0.9.16-beta" in wrong["a release tag different from VERSION"])
check("...the missing-from-released.js refusal says to deploy the site before Publish",
      "before Publish" in wrong["a release tag whose version isn't in released.js"])
for bad in ("v0.9", "v1", "0.9.16-beta", "mac-test-v0.9.16", "mac-test-v0.9.16-beta", "mac-test-v0.9.16-beta.", "mac-test-0.9.16-beta.1",
            "mac-test-v0.9.16-beta.1\nv0.9.16-beta", "mac-test-v0.9.16-rc.1", "latest", "", "v0.9.16-beta ", "v0.9.16-" + "a" * 30,
            "mac-test-v0.9.16-beta.1234"):
    check(f"a tag named {bad!r}: refused", isinstance(planned("tag", bad), str))
check("a Mac test version listed in released.js: refused (it must never be)",
      isinstance(planned("tag", "mac-test-v0.9.16-beta.1", released=RELEASED.replace('"0.9.16-beta"', '"0.9.16-mactest.1"')), str))
check("a maple_exp.py without exactly one VERSION line: refused",
      isinstance(planned("tag", "v0.9.16-beta", source="x = 1\r\n"), str)
      and isinstance(planned("tag", "v0.9.16-beta", source=SOURCE + SOURCE), str))

# ---- giving the test build its own version
new = rp.set_version(SOURCE.encode(), "0.9.16-mactest.1")
check("set-version changes only the VERSION line and keeps the line endings",
      new == b'import os\r\nVERSION = "0.9.16-mactest.1"\r\nWINDOW_TITLE = "x"\r\n')
check("...also with plain line endings", rp.set_version(b'a\nVERSION = "1.0"\nb\n', "2.0") == b'a\nVERSION = "2.0"\nb\n')
for bad_version in ("", "0.9.16 -beta", '1"; import os; "', "a" * 50, "1.0\nx"):
    try:
        rp.set_version(SOURCE.encode(), bad_version)
        refused = False
    except rp.PlanError:
        refused = True
    check(f"set-version refuses {bad_version[:20]!r}", refused)
try:
    rp.set_version(b"nothing here\n", "1.0")
    refused = False
except rp.PlanError:
    refused = True
check("set-version refuses a file with no VERSION line", refused)
check("the real maple_exp.py has exactly one VERSION line, and the tag mark is the same word in both files",
      rp.source_version((Path(rp.ROOT) / "maple_exp.py").read_text(encoding="utf-8")) == m.VERSION
      and rp.TEST_BUILD_MARK == m.TEST_BUILD_MARK)
check("the real released.js lists the real VERSION of a released build, never a mactest one",
      "-mactest" not in (Path(rp.ROOT) / "server" / "src" / "released.js").read_text(encoding="utf-8"))
check("every version a Mac test tag can make fits the overlay's own comparisons (no crash, older than its release)",
      m.version_key("0.9.16-mactest.1") < m.version_key("0.9.16") and m.version_key("0.9.16-mactest.1") > m.version_key("0.9.15-beta"))

# ---- a Mac test build sends nothing
real_version, real_urlopen = m.VERSION, m.urllib.request.urlopen
calls = []


def no_network(*a, **k):
    calls.append(a)
    raise AssertionError("the network was used")


m.urllib.request.urlopen = no_network
try:
    m.VERSION = "0.9.16-mactest.1"
    check("a Mac test build is blocked from sending", m.sharing_blocked())
    os.environ["MAPLE_EXP_ALLOW_SHARE"] = "1"                     # (what the tests use to send to a local server)
    check("...and MAPLE_EXP_ALLOW_SHARE doesn't open it", m.sharing_blocked())
    os.environ.pop("MAPLE_EXP_DATA")                              # a real player's setup: no test folder at all
    check("...nor does having no test data folder", m.sharing_blocked())
    senders = {
        "the update check": lambda: m.check_for_update(),
        "sharing runs": lambda: m.post_runs("a" * 32, [{"started": 1.0, "exp": 1, "seconds": 300}]),
        "a health report": lambda: m.post_health({"v": 2}),
        "Send report": lambda: m.post_report({"v": 1}),
    }
    for what, send in senders.items():
        try:
            send()
            answer = "sent"
        except RuntimeError:
            answer = "refused"
        except Exception as e:                                      # (anything else would be it getting past the gate)
            answer = f"got past the gate: {type(e).__name__}"
        check(f"{what}: refused in a Mac test build, with no network call", answer == "refused")
    check("...none of them touched the network", not calls)

    # A normal build without that mark is not blocked by the mark: only by the test data folder, as before.
    m.VERSION = "0.9.16-beta"
    check("a release build is not blocked by this rule (with MAPLE_EXP_ALLOW_SHARE set and no test folder)", not m.sharing_blocked())
    os.environ["MAPLE_EXP_DATA"] = str(m.DATA_DIR)
    os.environ.pop("MAPLE_EXP_ALLOW_SHARE")
    check("...and a test data folder still blocks it, as before", m.sharing_blocked())
    os.environ["MAPLE_EXP_ALLOW_SHARE"] = "1"
    check("...unless MAPLE_EXP_ALLOW_SHARE is set (how the sending tests work), as before", not m.sharing_blocked())
finally:
    m.VERSION, m.urllib.request.urlopen = real_version, real_urlopen
    os.environ.pop("MAPLE_EXP_ALLOW_SHARE", None)
    os.environ["MAPLE_EXP_DATA"] = str(m.DATA_DIR)

# A Mac test build leaves seen_version alone, so the release after it still shows its What's new.
from types import SimpleNamespace  # noqa: E402

shown = []
stand_in = SimpleNamespace(cfg=dict(m.load_config()), _fresh=False, _ask_to_share=lambda: shown.append("share"),
                           _whats_new=lambda notes, then: shown.append("notes"),
                           _shape_picker=lambda then: shown.append("picker"))
try:
    m.VERSION = "0.9.16-mactest.1"
    stand_in.cfg["seen_version"] = "0.9.15-beta"
    m.App._first_run(stand_in)
    check("a Mac test build doesn't store its version as seen", stand_in.cfg["seen_version"] == "0.9.15-beta")
    stand_in.cfg["seen_version"], stand_in._fresh = "", True
    m.App._first_run(stand_in)
    check("...nor on a new install (it still picks a shape)", stand_in.cfg["seen_version"] == "" and "picker" in shown)
    m.VERSION, stand_in._fresh = "0.9.16-beta", False
    stand_in.cfg["seen_version"] = "0.9.15-beta"
    m.App._first_run(stand_in)
    check("...while a release build still does", stand_in.cfg["seen_version"] == "0.9.16-beta")
    check("(why: a Mac test version sorts above its beta)", m.version_key("0.9.16-mactest.1") > m.version_key("0.9.16-beta"))
finally:
    m.VERSION = real_version

# In the Mac test build itself (the workflow runs this file again after release_plan.py set the version), the real
# VERSION must be blocked, whatever the environment says.
if m.TEST_BUILD_MARK in m.VERSION:
    os.environ["MAPLE_EXP_ALLOW_SHARE"] = "1"
    check("THIS build (a Mac test build) is blocked from sending, with MAPLE_EXP_ALLOW_SHARE set", m.sharing_blocked())
    os.environ.pop("MAPLE_EXP_ALLOW_SHARE")
    check("...and its VERSION is 'x.y.z-mactest.n'", __import__("re").fullmatch(r"\d+\.\d+\.\d+-mactest\.\d+", m.VERSION) is not None)

print(f"\n{failures} failure(s)" if failures else "\nall passed")
sys.exit(1 if failures else 0)
