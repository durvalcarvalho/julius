"""Guards the dependency DAG between layers. A violation here means a shortcut was taken."""

import ast
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "julius"

# layer -> layers it may import from (its own layer is always allowed)
ALLOWED_IMPORTS = {
    "config": set(),
    "domain": set(),
    "infra": {"domain", "config"},
    "parsers": {"domain"},
    "repositories": {"domain"},
    "services": {"domain", "config", "infra", "parsers", "repositories"},
    "cli": {"domain", "config", "infra", "services"},
}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _layer_of(module: str) -> str:
    return module.split(".")[1]


def _internal_imports(path: Path, module: str) -> set[str]:
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("julius."))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                found.add(f"{base}.{node.module}" if node.module else base)
            elif node.module and node.module.startswith("julius."):
                found.add(node.module)
    return found


def _modules() -> list[tuple[str, Path]]:
    return [(_module_name(p), p) for p in sorted(PACKAGE_DIR.rglob("*.py")) if _module_name(p) != "julius"]


def test_every_module_belongs_to_a_declared_layer():
    unknown = [name for name, _ in _modules() if _layer_of(name) not in ALLOWED_IMPORTS]
    assert unknown == [], f"add these to ALLOWED_IMPORTS with their dependency rules: {unknown}"


def test_layers_only_import_what_the_dag_allows():
    violations = []
    for name, path in _modules():
        layer = _layer_of(name)
        for imported in _internal_imports(path, name):
            target = _layer_of(imported)
            if target != layer and target not in ALLOWED_IMPORTS[layer]:
                violations.append(f"{name} -> {imported}")
    assert violations == [], "\n".join(violations)


def test_domain_imports_nothing_outside_the_standard_library():
    for name, path in _modules():
        if _layer_of(name) != "domain":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import | ast.ImportFrom) and not (
                isinstance(node, ast.ImportFrom) and node.level
            ):
                root = (node.names[0].name if isinstance(node, ast.Import) else node.module or "").split(".")[0]
                assert root in {"dataclasses", "typing", "__future__", "julius"}, f"{name} imports {root}"
