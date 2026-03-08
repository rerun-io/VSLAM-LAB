"""
check_dataset_files.py
----------------------
Loads and validates a VSLAM-LAB dataset .py + .yaml file pair.

Usage:
    python check_dataset_files.py \
        --py   dataset_hilti2026.py \
        --yaml dataset_hilti2026.yaml

Requires:
    pip install rich pyyaml pycodestyle
"""

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

console = Console()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def section(title: str) -> None:
    console.print()
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]", style="cyan"))

def ok(msg: str)       -> None: console.print(f"  [bold green]✓[/bold green] {msg}")
def warn(msg: str)     -> None: console.print(f"  [bold yellow]![/bold yellow] [yellow]{msg}[/yellow]")
def fail(msg: str)     -> None: console.print(f"  [bold red]✗[/bold red] {msg}")
def fail_red(msg: str) -> None: console.print(f"  [bold red]✗[/bold red] [red]{msg}[/red]")


# ──────────────────────────────────────────────
# 1. File existence
# ──────────────────────────────────────────────

def check_files_exist(py_path: Path, yaml_path: Path) -> bool:
    section("1. File existence")
    all_ok = True
    for p in (py_path, yaml_path):
        if p.exists():
            ok(f"Found: [dim]{p}[/dim]")
        else:
            fail(f"Missing: [dim]{p}[/dim]")
            all_ok = False
    return all_ok


# ──────────────────────────────────────────────
# 2. YAML loading
# ──────────────────────────────────────────────

def load_yaml(yaml_path: Path) -> dict | None:
    section("2. YAML loading")
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            fail("YAML root is not a mapping.")
            return None
        ok(f"Parsed successfully ([bold]{len(data)}[/bold] top-level keys).")
        return data
    except yaml.YAMLError as exc:
        fail(f"YAML parse error: {exc}")
        return None


# ──────────────────────────────────────────────
# 3. Python syntax check
# ──────────────────────────────────────────────

def check_python_syntax(py_path: Path) -> bool:
    section("3. Python syntax check")
    source = py_path.read_text(encoding="utf-8")
    try:
        ast.parse(source)
        ok("No syntax errors found.")
        return True
    except SyntaxError as exc:
        fail(f"Syntax error at line [bold]{exc.lineno}[/bold]: {exc.msg}")
        return False


# ──────────────────────────────────────────────
# 4. Python module import
# ──────────────────────────────────────────────

def load_python_module(py_path: Path):
    section("4. Python module import")
    spec = importlib.util.spec_from_file_location("_dataset_module", py_path)
    mod  = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        ok("Module imported successfully.")
        return mod
    except Exception as exc:
        warn(f"Import raised an exception (may be OK if deps are missing): [bold]{type(exc).__name__}[/bold]: {exc}")
        return None


# ──────────────────────────────────────────────
# 5. YAML required keys
# ──────────────────────────────────────────────

REQUIRED_YAML_KEYS = [
    "dataset_name",
    "rgb_hz",
    "modes",
    "cam_models",
    "sequence_names",
    "about",
    "vslamlab_maintainer",
]

def check_yaml_keys(data: dict) -> None:
    section("5. YAML required keys")
    for key in REQUIRED_YAML_KEYS:
        if key in data:
            ok(f"[dim]'{key}'[/dim] present")
        else:
            fail_red(f"[bold]'{key}'[/bold] MISSING")


# ──────────────────────────────────────────────
# 6. YAML value types & basic sanity
# ──────────────────────────────────────────────

def check_yaml_values(data: dict, py_path: Path, yaml_path: Path) -> None:
    section("6. YAML value sanity")

    # dataset_name
    name = data.get("dataset_name")
    if not isinstance(name, str) or not name:
        fail(f"dataset_name is invalid: {name!r}")
    else:
        ok(f"dataset_name = [bold]'{name}'[/bold]")
        expected_stem = f"dataset_{name}"
        for label, path in (("py", py_path), ("yaml", yaml_path)):
            if path.stem == expected_stem:
                ok(f"{label} filename matches dataset_name ([dim]'{path.name}'[/dim])")
            else:
                fail(f"{label} filename [bold]'{path.name}'[/bold] does not match expected [bold]'dataset_{name}{path.suffix}'[/bold]")

    # rgb_hz
    hz = data.get("rgb_hz")
    if isinstance(hz, (int, float)) and hz > 0:
        ok(f"rgb_hz = [bold]{hz}[/bold]")
    else:
        fail(f"rgb_hz is invalid: {hz!r}")

    # modes
    VALID_MODES = {"mono", "mono-vi", "rgbd", "rgbd-vi", "stereo", "stereo-vi"}
    modes = data.get("modes", [])
    if not isinstance(modes, list) or not modes:
        fail(f"modes is invalid or empty: {modes!r}")
    else:
        invalid = [m for m in modes if m not in VALID_MODES]
        if invalid:
            for m in invalid:
                fail_red(f"modes: [bold]'{m}'[/bold] is not a valid mode {sorted(VALID_MODES)}")
        else:
            ok(f"modes = [bold]{modes}[/bold]")

    # cam_models
    VALID_CAM_MODELS = {"pinhole", "radtan4", "radtan5", "radtan8", "equid4", "unknown"}
    cam_models = data.get("cam_models", [])
    if not isinstance(cam_models, list) or not cam_models:
        fail(f"cam_models is invalid or empty: {cam_models!r}")
    else:
        invalid = [m for m in cam_models if m not in VALID_CAM_MODELS]
        if invalid:
            for m in invalid:
                fail_red(f"cam_models: [bold]'{m}'[/bold] is not a valid model {sorted(VALID_CAM_MODELS)}")
        else:
            ok(f"cam_models = [bold]{cam_models}[/bold]")

    # url_download_root
    url = data.get("url_download_root", "")
    if isinstance(url, str) and url.startswith("http"):
        ok(f"url_download_root = [dim]'{url}'[/dim]")
    else:
        warn(f"url_download_root looks unusual: {url!r}")

    # sequence_names
    seqs = data.get("sequence_names", [])
    if isinstance(seqs, list) and seqs:
        ok(f"sequence_names: [bold]{len(seqs)}[/bold] sequences found")
    else:
        fail(f"sequence_names is invalid or empty: {seqs!r}")

    # about
    about = data.get("about", {})
    for sub in ("license", "summary", "homepage", "authors"):
        if sub in about:
            ok(f"about.[bold]{sub}[/bold] present")
        else:
            warn(f"about.[bold]{sub}[/bold] missing")

    # vslamlab_maintainer
    maint = data.get("vslamlab_maintainer", {})
    for sub in ("name", "email", "date"):
        if sub in maint:
            ok(f"vslamlab_maintainer.[bold]{sub}[/bold] = [dim]'{maint[sub]}'[/dim]")
        else:
            warn(f"vslamlab_maintainer.[bold]{sub}[/bold] missing")


# ──────────────────────────────────────────────
# 7. Required method definitions in .py
# ──────────────────────────────────────────────

REQUIRED_METHODS = [
    "download_sequence_data",
    "create_rgb_folder",
    "create_rgb_csv",
    "create_calibration_yaml",
    "create_groundtruth_csv",
]

OPTIONAL_METHODS = [
    "remove_unused_files",
    "get_download_issues",
]

VI_MODES = {"mono-vi", "rgbd-vi", "stereo-vi"}

def check_required_methods(py_path: Path, yaml_data: dict | None = None) -> None:
    section("7. Required method definitions")
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except SyntaxError:
        warn("Skipping method check — file has syntax errors.")
        return

    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }

    for method in REQUIRED_METHODS:
        if method in defined:
            ok(f"[dim]{method}[/dim] defined")
        else:
            fail_red(f"[bold]{method}[/bold] is NOT defined")

    # create_imu_csv is only required when a VI mode is present
    modes = set(yaml_data.get("modes", [])) if yaml_data else set()
    needs_imu = bool(modes & VI_MODES)
    if "create_imu_csv" in defined:
        ok(f"[dim]create_imu_csv[/dim] defined")
    elif needs_imu:
        fail_red(f"[bold]create_imu_csv[/bold] is NOT defined (required for VI modes: {sorted(modes & VI_MODES)})")
    else:
        warn(f"[bold]create_imu_csv[/bold] is not defined (not required — no VI modes detected)")

    for method in OPTIONAL_METHODS:
        if method in defined:
            ok(f"[dim]{method}[/dim] defined")
        else:
            warn(f"[bold]{method}[/bold] is not defined (optional)")


# ──────────────────────────────────────────────
# 9. os.path.join usage
# ──────────────────────────────────────────────

def check_os_path_join(py_path: Path) -> None:
    section("9. os.path.join usage")
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except SyntaxError:
        warn("Skipping os.path.join check — file has syntax errors.")
        return

    hits: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "path"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "os"
        ):
            hits.append(node.lineno)

    if not hits:
        ok("No [dim]os.path.join[/dim] usage found — [bold]Path[/bold] library used correctly.")
    else:
        for lineno in hits:
            fail_red(f"[bold]os.path.join[/bold] found at line [bold]{lineno}[/bold] — use [bold]Path / operator[/bold] instead")


# ──────────────────────────────────────────────
# 8. PEP 8 compliance
# ──────────────────────────────────────────────

PEP8_SHOW_LIMIT = 5

def check_pep8(py_path: Path) -> None:
    section("8. PEP 8 compliance")
    try:
        import pycodestyle
    except ImportError:
        warn("pycodestyle not installed — skipping. Run: [bold]pip install pycodestyle[/bold]")
        return

    violations: list[str] = []

    class _Collector(pycodestyle.BaseReport):
        def error(self, line_number, offset, text, check):
            violations.append(f"line {line_number}:{offset + 1}  {text}")
            return super().error(line_number, offset, text, check)

    style = pycodestyle.StyleGuide(reporter=_Collector, quiet=True, max_line_length=120)
    style.check_files([str(py_path)])

    total = len(violations)
    if total == 0:
        ok("No PEP 8 violations found.")
        return

    shown = violations[:PEP8_SHOW_LIMIT]
    remaining = total - PEP8_SHOW_LIMIT

    for v in shown:
        warn(v)
    if remaining > 0:
        warn(f"... and [bold]{remaining}[/bold] more violation{'s' if remaining > 1 else ''} (total: {total})")
    else:
        warn(f"Total: [bold]{total}[/bold] violation{'s' if total > 1 else ''}")

    console.print()
    console.print("  [bold yellow]To fix automatically, run:[/bold yellow]")
    console.print(f"    [dim]ruff check {py_path} --line-length 120[/dim]")
    console.print(f"    [dim]ruff format {py_path} --line-length 120[/dim]")
    console.print(f"    [dim]isort {py_path}[/dim]")

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

DATASET_FILES_SUBDIR = Path("Datasets") / "dataset_files"

# Script lives at VSLAM-LAB/Utilities/check_dataset.py → root is one level up
VSLAM_LAB_ROOT = Path(__file__).resolve().parent.parent
if str(VSLAM_LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(VSLAM_LAB_ROOT))


def resolve_dataset_paths(dataset_name: str) -> tuple[Path, Path]:
    """Resolve .py and .yaml paths from dataset name using VSLAM_LAB_PATH."""
    try:
        from path_constants import VSLAM_LAB_DIR
        base = Path(VSLAM_LAB_DIR) / DATASET_FILES_SUBDIR
    except ImportError:
        console.print("  [bold yellow]![/bold yellow] [yellow]path_constants not found — falling back to project root[/yellow]")
        base = VSLAM_LAB_ROOT / DATASET_FILES_SUBDIR

    py_path   = base / f"dataset_{dataset_name}.py"
    yaml_path = base / f"dataset_{dataset_name}.yaml"
    return py_path, yaml_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a VSLAM-LAB dataset .py + .yaml pair.")
    parser.add_argument("dataset_name", type=str, help="Dataset name, e.g. 'hilti2026'")
    args = parser.parse_args()

    py_path, yaml_path = resolve_dataset_paths(args.dataset_name)

    console.print()
    console.print(Panel.fit(
        f"[bold]dataset[/bold] → [dim]{args.dataset_name}[/dim]\n"
        f"[bold]py[/bold]      → [dim]{py_path}[/dim]\n"
        f"[bold]yaml[/bold]    → [dim]{yaml_path}[/dim]",
        title="[bold cyan]Dataset File Checker[/bold cyan]",
        border_style="cyan",
    ))

    if not check_files_exist(py_path, yaml_path):
        sys.exit(1)

    yaml_data = load_yaml(yaml_path)
    check_python_syntax(py_path)
    load_python_module(py_path)
    check_required_methods(py_path, yaml_data)
    check_os_path_join(py_path)
    check_pep8(py_path)

    if yaml_data is not None:
        check_yaml_keys(yaml_data)
        check_yaml_values(yaml_data, py_path, yaml_path)

    console.print()
    console.print(Rule("[bold cyan]Done[/bold cyan]", style="cyan"))
    console.print()


if __name__ == "__main__":
    main()