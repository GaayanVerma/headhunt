"""Unit tests for linkedin_scraper.github.skills manifest parsing."""

import pytest

from linkedin_scraper.github.skills import (
    _parse_package_json,
    _parse_requirements_txt,
    _parse_pyproject_toml,
    _parse_go_mod,
    _parse_gemfile,
    extract_repo_frameworks,
)


@pytest.mark.unit
class TestManifestParsers:
    def test_parse_package_json(self):
        content = '{"dependencies": {"react": "^18.0.0", "left-pad": "1.0.0"}, "devDependencies": {"jest": "^29.0.0"}}'
        names = _parse_package_json(content)
        assert set(names) == {"react", "left-pad", "jest"}

    def test_parse_package_json_malformed(self):
        assert _parse_package_json("not json") == []

    def test_parse_requirements_txt(self):
        content = "django==4.2\nrequests>=2.0\n# a comment\n-e .\nnumpy"
        names = _parse_requirements_txt(content)
        assert names == ["django", "requests", "numpy"]

    def test_parse_pyproject_toml_poetry(self):
        content = (
            "[tool.poetry.dependencies]\n"
            'python = "^3.11"\n'
            'fastapi = "^0.100"\n'
            'sqlalchemy = "^2.0"\n'
            "[tool.poetry.dev-dependencies]\n"
            'pytest = "^7.0"\n'
        )
        names = _parse_pyproject_toml(content)
        assert "fastapi" in names
        assert "sqlalchemy" in names
        assert "pytest" in names
        assert "python" not in names

    def test_parse_go_mod(self):
        content = (
            "module example.com/foo\n\n"
            "require (\n"
            "\tgithub.com/gin-gonic/gin v1.9.0\n"
            "\tgithub.com/pkg/errors v0.9.1\n"
            ")\n"
        )
        names = _parse_go_mod(content)
        assert "gin" in names or "github.com/gin-gonic/gin" in names

    def test_parse_gemfile(self):
        content = 'source "https://rubygems.org"\ngem "rails", "~> 7.0"\ngem \'sinatra\'\n'
        names = _parse_gemfile(content)
        assert set(names) == {"rails", "sinatra"}


@pytest.mark.unit
class TestExtractRepoFrameworks:
    def test_filters_to_allowlist(self):
        manifest_contents = {
            "package.json": '{"dependencies": {"react": "^18.0.0", "some-random-utility-lib": "1.0.0"}}',
        }
        frameworks = extract_repo_frameworks(manifest_contents)
        assert frameworks == ["react"]

    def test_dedupes_across_manifests(self):
        manifest_contents = {
            "requirements.txt": "django\nflask",
            "pyproject.toml": "[tool.poetry.dependencies]\ndjango = \"^4.0\"\n",
        }
        frameworks = extract_repo_frameworks(manifest_contents)
        assert frameworks.count("django") == 1
        assert "flask" in frameworks

    def test_unknown_manifest_ignored(self):
        assert extract_repo_frameworks({"cargo.toml": "[dependencies]\nserde = \"1.0\""}) == []

    def test_empty_input(self):
        assert extract_repo_frameworks({}) == []
