import os

import project_context


def test_find_project_root_uses_git(tmp_path):
    root = tmp_path / "repo"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    assert project_context.find_project_root(nested) == str(root.resolve())


def test_load_project_context_reads_known_files(tmp_path):
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    ctx = project_context.load_project_context(tmp_path)
    assert ctx.root == str(tmp_path.resolve())
    assert os.path.join(str(tmp_path.resolve()), "README.md") in ctx.files
    assert "hello" in ctx.text
