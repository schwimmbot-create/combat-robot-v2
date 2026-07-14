from __future__ import annotations

import ast
from pathlib import Path


def test_drive_sim_tests_do_not_import_from_tools_namespace():
    for path in Path("tests/unit").glob("test_drive_sim*.py"):
        tree = ast.parse(path.read_text())
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        assert not any(
            (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tools.drive_sim"))
            or (isinstance(node, ast.Import) and any(alias.name.startswith("tools.drive_sim") for alias in node.names))
            for node in imports
        ), f"{path} should add tools/ to sys.path and import drive_sim.*"
