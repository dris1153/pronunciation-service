"""English docs carry a content-hash rev; translations are matched against it (see AGENTS.md)."""
import importlib.util
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("docs_sync", ROOT / "scripts" / "docs_sync.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def test_english_revs_and_status_are_current():
    errors, _ = sync.check()
    assert not errors, "\n".join(errors) + "\nFix: python scripts/docs_sync.py bump"


def test_stale_translations_warn_but_do_not_fail():
    _, stale = sync.check()
    for message in stale:
        warnings.warn(f"stale translation: {message}", stacklevel=1)


def test_rev_ignores_id_line_and_line_endings():
    body = "# Title\n\ntext\n"
    rev = sync.compute_rev(body)
    assert sync.compute_rev("<!-- doc-id: x | rev: 00000000 -->\n" + body) == rev
    assert sync.compute_rev(body.replace("\n", "\r\n")) == rev
    assert sync.compute_rev(body + "more\n") != rev


def test_links_are_rewritten_for_translation_folder():
    fixed = sync._fix_links(
        "[a](../LICENSE) [b](scoring-v2.md#x) [c](../app/core/config.py) [d](https://x.io) [e](#top)\n"
        "```\n[skip](../LICENSE)\n```\n",
        "vi", "docs/api.md",
    )
    assert "[a](../../../LICENSE)" in fixed
    assert "[b](scoring-v2.md#x)" in fixed  # translated doc, same relative position
    assert "[c](../../../app/core/config.py)" in fixed
    assert "[d](https://x.io)" in fixed and "[e](#top)" in fixed
    assert "[skip](../LICENSE)" in fixed  # code fences are untouched
    assert sync._fix_links(fixed, "vi", "docs/api.md") == fixed  # idempotent
