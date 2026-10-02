"""Check repository metadata without importing Home Assistant or using a network."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_structure() -> None:
    """Keep the HACS scaffold valid while allowing future integration modules."""
    components = ROOT / "custom_components"
    integration = components / "hoben"
    assert integration.is_dir()
    assert (integration / "__init__.py").is_file()
    manifest_path = integration / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)
    assert manifest["domain"] == "hoben"
    assert manifest["name"] == "Hoben"
    assert manifest["iot_class"] == "cloud_polling"
    # Accept SemVer releases and prereleases, without pinning the bootstrap version.
    number = r"(?:0|[1-9][0-9]*)"
    identifier = rf"(?:{number}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    version_pattern = (
        rf"{number}\.{number}\.{number}"
        rf"(?:-{identifier}(?:\.{identifier})*)?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    )
    assert isinstance(manifest["version"], str)
    assert re.fullmatch(version_pattern, manifest["version"])
    for key in ("documentation", "issue_tracker"):
        assert isinstance(manifest[key], str)
        assert manifest[key].startswith("https://")
    assert isinstance(manifest["codeowners"], list)
    assert manifest["codeowners"]
    assert all(isinstance(owner, str) and owner for owner in manifest["codeowners"])
    integrations = {
        path.name
        for path in components.iterdir()
        if path.is_dir() and not path.name.startswith((".", "__"))
    }
    assert integrations == {"hoben"}
    hacs_path = ROOT / "hacs.json"
    assert hacs_path.is_file()
    hacs = json.loads(hacs_path.read_text(encoding="utf-8"))
    assert isinstance(hacs, dict)
    assert hacs["name"] == "Hoben"
    assert (ROOT / "README.md").is_file()
