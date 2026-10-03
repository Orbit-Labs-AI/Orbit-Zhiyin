import pytest

from orbit_catalog.contracts import SourceSpec
from orbit_catalog.sources.github import GitHubConnector, file_kind

from .test_sources import FakeGitHub


def test_explicit_revision_uses_commit_endpoint_and_stays_pinned():
    sha = "b" * 40

    class PinnedHTTP(FakeGitHub):
        def __init__(self):
            super().__init__({"skills/a/SKILL.md": "---\nname: a\n---\nbody"}, sha)
            self.urls = []

        def json(self, url, immutable=False):
            self.urls.append(url)
            if "/commits/" in url:
                assert immutable and url.endswith(sha)
                return {"sha": sha, "commit": {"committer": {"date": "2026-10-01T00:00:00Z"}}}
            return super().json(url, immutable=immutable)

    http = PinnedHTTP()
    spec = SourceSpec(source_id="pin", kind="github", url="https://github.com/a/b",
                      config={"repo": "a/b", "revision": sha})
    first = GitHubConnector(spec, http).fetch_page({}, {})
    assert first.complete and first.revision == sha
    assert first.records[0].resource.commit_sha == sha
    assert not any("/branches/" in url for url in http.urls)
    unchanged = GitHubConnector(spec, http).fetch_page({}, {"revision": sha})
    assert unchanged.complete and unchanged.mode == "incremental" and not unchanged.records
    with pytest.raises(ValueError, match="git_revision_checkpoint_mismatch"):
        GitHubConnector(spec, http).fetch_page({"sha": "a" * 40}, {})


@pytest.mark.parametrize("revision", ["main", "v1", "a" * 39, "A" * 40, 123])
def test_revision_must_be_full_lowercase_commit_sha(revision):
    spec = SourceSpec(source_id="pin", kind="github", url="https://github.com/a/b",
                      config={"repo": "a/b", "revision": revision})
    with pytest.raises(ValueError, match="invalid_git_revision"):
        GitHubConnector(spec, None)


def test_standalone_override_is_explicit_and_ignore_has_priority():
    path = ".github/workflows/review.md"
    rule = {"glob": ".github/workflows/*.md", "type": "workflow"}
    assert file_kind(path, {"."}, [rule]) is None
    assert file_kind(path, {"."}, [{**rule, "standalone": True}]) == "workflow"
    assert file_kind(path, {"."}, [{**rule, "standalone": "true"}]) is None
    rules = [{**rule, "standalone": True}, {"glob": ".github/workflows/shared/**", "type": "ignore"}]
    assert file_kind(".github/workflows/shared/auth.md", {"."}, rules) is None
    assert file_kind(".github/workflows/shared/README.md", {"."}, rules) is None
    assert file_kind("SKILL.md", set(), [{"glob": "SKILL.md", "type": "ignore"}]) is None
    assert file_kind("SKILL.md", set(), [{"glob": "**", "type": "workflow", "standalone": True}]) == "skill"
