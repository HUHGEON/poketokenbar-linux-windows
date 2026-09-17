"""The extension's JavaScript parses, and its manifest is well formed.

GNOME Shell reports a syntax error only in the journal, after the extension has
already failed to load, so a stray character survives right up until someone
tries it on a real desktop. Node parses the same ESM grammar GJS does, which is
enough to catch that class without a Shell.

It is a parse check, not a run: nothing here proves an actor renders or that a
GNOME API exists. What it does mean is that a typo cannot reach a release.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

EXTENSION_DIR = (
    Path(__file__).resolve().parent.parent
    / "gnome-extension"
    / "poketokenbar@huhgeon.github.io"
)

NODE = shutil.which("node")


def js_files():
    return sorted(EXTENSION_DIR.rglob("*.js"))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_each_file_parses(path):
    # Copied to .mjs so Node applies module grammar; the sources keep the .js
    # name GNOME Shell requires.
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / f"{path.stem}.mjs"
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        result = subprocess.run(
            [NODE, "--check", str(target)], capture_output=True, text=True
        )
    assert result.returncode == 0, f"{path.name} does not parse:\n{result.stderr}"


def test_the_manifest_is_valid_and_declares_what_shell_needs():
    metadata = json.loads((EXTENSION_DIR / "metadata.json").read_text(encoding="utf-8"))
    for key in ("uuid", "name", "description", "shell-version"):
        assert metadata.get(key), f"metadata.json has no {key}"
    assert metadata["uuid"] == EXTENSION_DIR.name, (
        "the uuid and the directory name must match or Shell will not load it"
    )
    assert all(v.isdigit() for v in metadata["shell-version"])


def test_the_manifest_declares_no_schema_it_does_not_ship():
    """Declaring settings-schema without installing the schema makes
    getSettings() throw the first time a preferences window opens."""
    metadata = json.loads((EXTENSION_DIR / "metadata.json").read_text(encoding="utf-8"))
    schema = metadata.get("settings-schema")
    if not schema:
        return
    schemas = list(EXTENSION_DIR.rglob("*.gschema.xml"))
    assert schemas, f"metadata declares {schema} but no schema is shipped"


def test_the_entry_point_default_exports_an_extension():
    source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
    assert re.search(r"export\s+default\s+class\s+\w+\s+extends\s+Extension", source), (
        "GNOME 45+ loads the default export of extension.js"
    )
    assert "enable()" in source and "disable()" in source


def test_the_loader_imports_the_current_ui_on_every_enable():
    """extension.js is cached for the whole session, so it must not import the
    UI statically: a static import would pin the popup to the code the session
    started with, and an update would need a new session again."""
    source = (EXTENSION_DIR / "extension.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    assert not re.search(r"^import .* from '\./lib/", code, re.M), (
        "extension.js imports the UI statically; the UI has to be loaded in enable()")
    enable = code.split("    enable() {")[1].split("    disable() {")[0]
    disable = code.split("    disable() {")[1]
    assert "import(" in enable and "'current'" in code
    # A late import after disable() must not bring the UI back.
    assert "generation !== this._generation" in enable
    assert "this._main?.disable()" in disable
    # The name read from disk can only pick a lib directory beside the loader.
    assert "UI_DIRECTORY.test(name)" in code


def test_everything_enable_starts_is_torn_down_in_disable():
    """A timer or signal left connected leaks inside the compositor, where the
    only way out is a session restart."""
    source = (EXTENSION_DIR / "lib" / "main.js").read_text(encoding="utf-8")
    # Comments first: the file's own header describes this rule in prose, and
    # splitting on the word would cut the body at the sentence instead.
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"//[^\n]*", "", source)
    enable = source.split("enable()")[1].split("disable()")[0]
    disable = source.split("disable()")[1]

    for handler in re.findall(r"this\.(_\w*[Hh]andler)\s*=", enable):
        assert f"disconnect(this.{handler})" in disable, f"{handler} is never disconnected"
    if "new StateReader" in enable:
        assert "stop()" in disable, "the state reader's timer is never stopped"
    assert "this._indicator?.destroy()" in disable, "_indicator is never destroyed"
    # The pet is in chrome, so it has to be removed from the layout manager as
    # well as destroyed; _removePet does both and disable() must call it.
    assert "_removePet()" in disable, "_pet is never torn down"
    assert "removeChrome" in source, "the pet is never taken out of chrome"


def test_the_stylesheet_is_present():
    """Shell loads stylesheet.css by name; without it every style_class here
    resolves to nothing and the popup renders unstyled.

    Its contents are not asserted: no check available from here can tell a
    valid St rule from one Shell will ignore, and a test that only restates the
    file would fail on every edit while catching nothing.
    """
    css = (EXTENSION_DIR / "stylesheet.css").read_text(encoding="utf-8")
    assert css.strip()
    assert ".poketokenbar-panel" in css


def test_no_source_file_is_empty():
    for path in js_files():
        assert path.read_text(encoding="utf-8").strip(), f"{path.name} is empty"


def test_the_manifest_covers_the_current_gnome_releases():
    """An extension whose shell-version omits the running Shell is hidden
    entirely — no error, no entry in the list, nothing to click.

    This was the first thing a real install hit. GNOME ships twice a year, so
    the range needs widening on a schedule rather than when someone reports it.
    """
    metadata = json.loads((EXTENSION_DIR / "metadata.json").read_text(encoding="utf-8"))
    declared = {int(v) for v in metadata["shell-version"]}
    # 45 is where ESM extensions begin; anything older needs a different entry
    # point entirely.
    assert min(declared) == 45
    # Contiguous: a gap silently excludes that release.
    assert declared == set(range(min(declared), max(declared) + 1))
    # Current stable at the time of writing is 50, with 51 due September 2026.
    assert max(declared) >= 51


def test_no_caller_options_are_spread_into_a_gobject_constructor():
    """`super._init({...params})` hands the caller's whole option bag to GObject.

    This is what actually broke the first real install. `new Sprite({size: 18})`
    looked like a local option, but Clutter.Actor already has a `size` property
    whose type is the boxed graphene_size_t — so every sprite constructed threw
    "Wrong type number; boxed type GrapheneSize expected", and since the panel
    builds a sprite first, the extension never started at all.

    Nothing available here can ask GObject which names are real, so the rule is
    structural instead: destructure your own options out before the spread.
    """
    offenders = []
    for path in js_files():
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"super\._init\(\{(.*?)\}\);", source, re.S):
            body = match.group(1)
            if re.search(r"\.\.\.params\b", body):
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{path.name}:{line}")
    assert not offenders, (
        "these spread the caller's options straight into GObject: "
        f"{offenders}. Destructure your own keys out first — a name that "
        "collides with a real property fails at construction."
    )


# MARK: identifiers


# Names that exist without being imported: GJS globals, JavaScript built-ins,
# and the handful the Shell injects.
_AMBIENT = {
    "Math", "JSON", "Object", "Array", "String", "Number", "Boolean", "Date",
    "Error", "TypeError", "Promise", "Set", "Map", "RegExp", "Symbol",
    "TextDecoder", "TextEncoder", "Infinity", "NaN",
    # GJS
    "imports", "log", "logError", "print", "printerr", "globalThis", "global",
    "ARGV", "pkg",
}


def _imported_names(source: str) -> set[str]:
    names = set()
    # import X from '...'
    names.update(re.findall(r"^import\s+(\w+)\s+from", source, re.M))
    # import * as X from '...'
    names.update(re.findall(r"^import\s+\*\s+as\s+(\w+)\s+from", source, re.M))
    # import {A, B as C} from '...'
    for group in re.findall(r"^import\s+\{([^}]*)\}\s+from", source, re.M | re.S):
        for part in group.split(","):
            part = part.strip()
            if not part:
                continue
            names.add(part.split(" as ")[-1].strip())
    return names


def _declared_names(source: str) -> set[str]:
    names = set()
    names.update(re.findall(r"\b(?:const|let|var)\s+(\w+)", source))
    names.update(re.findall(r"\bfunction\s+(\w+)", source))
    names.update(re.findall(r"\bclass\s+(\w+)", source))
    # export const X = GObject.registerClass(class X extends ...)
    names.update(re.findall(r"^export\s+(?:const|let|function|class)\s+(\w+)", source, re.M))
    # destructuring: const {a, b} = ...
    for group in re.findall(r"(?:const|let|var)\s*\{([^}]*)\}\s*=", source):
        for part in group.split(","):
            part = part.strip().split(":")[-1].split("=")[0].strip().lstrip(".")
            if part.isidentifier():
                names.add(part)
    return names


@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_every_namespace_used_is_imported(path):
    """A namespace used but not imported is a ReferenceError at load.

    This is the failure mode that matters most here, because it cannot be seen
    by reading and there is no Shell available to run into it: removing an
    import while leaving one use behind leaves an extension that parses
    perfectly and then does not start.
    """
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r"'[^'\n]*'|\"[^\"\n]*\"|`[^`]*`", "''", source, flags=re.S)

    known = _imported_names(source) | _declared_names(source) | _AMBIENT
    # A capitalised name followed by a dot is a namespace or a class in use.
    used = set(re.findall(r"(?<![.\w])([A-Z]\w*)\s*\.", source))
    # Class bodies refer to their own name via `extends`, and to enum-like
    # constants declared in the same file.
    missing = used - known
    assert not missing, f"{path.name} uses {sorted(missing)} without importing it"


@pytest.mark.parametrize("path", js_files(), ids=lambda p: p.name)
def test_no_import_is_left_unused(path):
    """An unused import is dead weight, and usually the leftover of a change
    that removed the last use — which is worth noticing while it is still
    harmless rather than after the reverse mistake."""
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"^import[^;]*;", "", source, flags=re.M | re.S)
    for name in _imported_names(path.read_text(encoding="utf-8")):
        assert re.search(rf"(?<![.\w]){re.escape(name)}\b", source), (
            f"{path.name} imports {name} and never uses it"
        )
