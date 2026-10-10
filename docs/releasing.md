# Releasing Gentui to PyPI

Releases are published by [`.github/workflows/release.yml`](https://github.com/rahrajlat/Gentui/blob/main/.github/workflows/release.yml) using PyPI
**trusted publishing**: GitHub proves its identity to PyPI, so there is no API token to create, store or leak.

## One-time setup

1. **Create accounts** on [pypi.org](https://pypi.org) and, for dry runs, [test.pypi.org](https://test.pypi.org). Turn on 2FA.
2. **Register the project as a pending trusted publisher** (this reserves the name `gentui` for you):
   PyPI → *Your account* → *Publishing* → *Add a new pending publisher*:

   | Field | Value |
   |---|---|
   | PyPI project name | `gentui` |
   | Owner | `rahrajlat` |
   | Repository name | `Gentui` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   Repeat on TestPyPI with environment name `testpypi`.
3. **Create the two environments** in GitHub: *Settings → Environments* → `pypi` and `testpypi`. On `pypi`, add yourself
   as a *required reviewer* so a release cannot go out without your approval.

## Dry run on TestPyPI (recommended first)

GitHub → *Actions* → **Release** → *Run workflow* → choose `testpypi`. Then, in a clean directory:

```bash
# with uv
uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ gentui --version

# with pip (in a fresh virtual environment)
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ gentui
gentui --version
```

**Always add the `--extra-index-url https://pypi.org/simple/` part.** Gentui's dependencies are not on TestPyPI, and the
few that are there are junk placeholders. For example TestPyPI's `ag-ui-protocol` only has thousands of `0.0.0.devNNN`
builds and nothing at `1.0.0`. Installing from TestPyPI alone fails with:

```
ERROR: Could not find a version that satisfies the requirement ag-ui-protocol>=1.0.0 (from versions: 0.0.0.dev...)
```

That error is a TestPyPI quirk, not a problem with the package. On the real PyPI, `pip install gentui` has no such issue.

## Real release

1. Update `version` in `pyproject.toml` and the top entry of [`CHANGELOG.md`](https://github.com/rahrajlat/Gentui/blob/main/CHANGELOG.md) (replace "Unreleased" with the date).
2. Commit, and make sure CI is green on `main`.
3. Tag and push the tag. The tag must be `v` plus the exact version:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Approve the `pypi` environment when GitHub asks. The workflow runs the tests, builds, runs `twine check`, and publishes.
5. Check https://pypi.org/project/gentui/ and try it: `uvx gentui --version`.

**A published version can never be replaced or reused.** If something is wrong, fix it and release the next version
(you can *yank* a bad release on PyPI so people stop installing it).

## After each release

- Check https://pypi.org/project/gentui/ renders correctly (the README shown there is the one from the release, so a
  README fix only appears on PyPI with the next version).
- Create a GitHub Release from the tag and paste the changelog entry.
- Move the changelog's next entry to the top as "Unreleased".

`0.1.0` was published to PyPI on 2026-10-05.
