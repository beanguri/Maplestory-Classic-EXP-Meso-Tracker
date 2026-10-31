"""What a GitHub Build run is making, decided from the tag that started it (used by .github/workflows/build.yml).

  python release_plan.py plan <ref_type> <ref_name>   prints kind= / tag= / version= lines for $GITHUB_OUTPUT;
                                                      exits 1 with the reason when the tag is wrong
  python release_plan.py set-version <version>        rewrites VERSION in maple_exp.py (Mac test builds)

Three kinds of run:
  release   a tag like v0.9.16-beta. Windows + both Macs, ONE draft release. The tag must equal VERSION in
            maple_exp.py and VERSION must be listed in server/src/released.js (the site takes runs and reports only
            from listed versions).
  mactest   a tag like mac-test-v0.9.16-beta.1. Macs only, a draft PRE-release. The build calls itself
            0.9.16-mactest.1 (never listed in released.js) and maple_exp.sharing_blocked() makes it send nothing.
  branch    "Run workflow" on a branch: builds and keeps the files on the run's page, no release.

Only the standard library, so the first (read-only) job can run it without installing anything.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

RELEASE_TAG = re.compile(r"v(\d{1,4}\.\d{1,4}\.\d{1,4}(?:-[A-Za-z0-9.]{1,20})?)")
MACTEST_TAG = re.compile(r"mac-test-v(\d{1,4}\.\d{1,4}\.\d{1,4})-beta\.(\d{1,3})")
TEST_BUILD_MARK = "-mactest"          # the same word as maple_exp.TEST_BUILD_MARK (a test keeps them equal)


class PlanError(Exception):
    pass


def source_version(text):
    """VERSION = "..." from maple_exp.py's text."""
    found = re.findall(r'^VERSION = "([^"]+)"', text, re.M)
    if len(found) != 1:
        raise PlanError(f"expected one VERSION line in maple_exp.py, found {len(found)}")
    return found[0]


def plan(ref_type, ref_name, source_text, released_text):
    """{"kind", "tag", "version"} for this run, or PlanError. `source_text` is maple_exp.py, `released_text` is
    server/src/released.js."""
    version = source_version(source_text)
    if ref_type != "tag":
        return {"kind": "branch", "tag": "", "version": version}
    mac = MACTEST_TAG.fullmatch(ref_name)
    if mac:
        test_version = f"{mac[1]}{TEST_BUILD_MARK}.{mac[2]}"
        if f'"{test_version}"' in released_text:
            raise PlanError(f"{test_version} is listed in server/src/released.js: a Mac test build must never be")
        return {"kind": "mactest", "tag": ref_name, "version": test_version}
    rel = RELEASE_TAG.fullmatch(ref_name)
    if not rel:
        raise PlanError(f"{ref_name} is neither a release tag (v0.9.16-beta) nor a Mac test tag (mac-test-v0.9.16-beta.1)")
    if TEST_BUILD_MARK in rel[1]:
        raise PlanError(f"{ref_name} has {TEST_BUILD_MARK} in it, which only Mac test builds may")
    if rel[1] != version:
        raise PlanError(f"The tag is {ref_name} but maple_exp.py says VERSION = {version}. Fix one, and tag again.")
    # mcwo.app takes runs and reports only from the versions in server/src/released.js.
    if f'"{version}"' not in released_text:
        raise PlanError(f"VERSION {version} is missing from server/src/released.js: add it, deploy the site before "
                        "Publish, and tag again.")
    return {"kind": "release", "tag": ref_name, "version": version}


def set_version(source_bytes, version):
    """maple_exp.py's bytes with the VERSION line replaced (line endings kept)."""
    if not re.fullmatch(r"[0-9A-Za-z.\-]{1,40}", version):
        raise PlanError(f"odd version {version[:50]!r}")
    new, n = re.subn(rb'^VERSION = "[^"\r\n]+"', b'VERSION = "' + version.encode() + b'"', source_bytes, flags=re.M)
    if n != 1:
        raise PlanError(f"expected one VERSION line in maple_exp.py, found {n}")
    return new


def main(argv):
    try:
        if argv[:1] == ["plan"] and len(argv) == 3:
            got = plan(argv[1], argv[2], (ROOT / "maple_exp.py").read_text(encoding="utf-8"),
                       (ROOT / "server" / "src" / "released.js").read_text(encoding="utf-8"))
            for key in ("kind", "tag", "version"):
                print(f"{key}={got[key]}")
            return 0
        if argv[:1] == ["set-version"] and len(argv) == 2:
            path = ROOT / "maple_exp.py"
            path.write_bytes(set_version(path.read_bytes(), argv[1]))
            print(f'maple_exp.py now says VERSION = "{argv[1]}"')
            return 0
    except PlanError as e:
        print(f"::error::{e}")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
