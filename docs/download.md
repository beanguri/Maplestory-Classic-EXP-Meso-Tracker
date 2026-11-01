# Where the download comes from

Downloads on the [Releases page](https://github.com/beanguri/Maple-Classic-Exp-Overlay/releases) are built by GitHub from the code in this repository ([Build workflow](../.github/workflows/build.yml)), not on anyone's own PC. Each build:

- installs exact package files, each checked against its SHA-256 ([requirements-build.txt](../requirements-build.txt)),
- runs all the tests,
- records a signed **attestation**: which workflow built which file, from which commit,
- puts each file's **SHA-256** on the release page (`SHA256SUMS.txt`): the Windows zip and, since v0.9.16, the two Mac .dmg files.

**Check your download** with the free [GitHub CLI](https://cli.github.com):

```
gh attestation verify "the file you downloaded" --repo beanguri/Maple-Classic-Exp-Overlay
```

It tells you whether that exact file was built here, and from which commit. Or compare the file's SHA-256 with `SHA256SUMS.txt` on its release page (in PowerShell: `Get-FileHash "the file you downloaded"`; on a Mac, in Terminal: `shasum -a 256 "the file you downloaded"`).

The same files are also kept on the page of the build that made them (Actions, the run, the file at the bottom; you need a GitHub account to download it). Build runs since October 17 keep them exactly as they are, so the SHA-256 GitHub shows there is the file's own, the same as on the release page.

**About v0.9.6:** it was built by GitHub from its tag, before the package checks and attestations were added, so it has no attestation. Its SHA-256 is on its release page. [Its build's page](https://github.com/beanguri/Maple-Classic-Exp-Overlay/actions/runs/38631744258) keeps the zip inside an extra zip (GitHub does that unless told not to), so the SHA-256 shown *there* is for that outer zip and won't match: extract it once, and the zip inside has the release's SHA-256. That page keeps it until January 2027. Versions before v0.9.6 were built on my PC.

The code signing policy is in the [README](../README.md#code-signing-policy).
