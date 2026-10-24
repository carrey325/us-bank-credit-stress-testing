"""Execute exactly three guides in fresh kernels using only public repository inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

GUIDES = (
    "01_call_reports_to_credit_losses.ipynb",
    "02_benchmarks_and_forecast_evidence.ipynb",
    "03_ci_stress_scenario_walkthrough.ipynb",
)
PROTECTED = ("results", "metadata", "data/manifests", "configs")


def protected_hashes(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in PROTECTED for path in sorted((root / directory).rglob("*")) if path.is_file()}


def run_guides(root: Path, *, cwd: str = "root", write: bool = False) -> None:
    """Stage public inputs and keep original notebooks untouched on execution failure."""
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client import KernelManager
    from jupyter_client.kernelspec import KernelSpecManager

    root = Path(root).resolve()
    if cwd not in {"root", "notebooks"}:
        raise ValueError("cwd must be root or notebooks")
    before = protected_hashes(root)
    executed = []
    with tempfile.TemporaryDirectory(prefix="bankstress-guides-") as temporary:
        stage = Path(temporary)
        repo = stage / "repository"
        repo.mkdir()
        for directory in (*PROTECTED, "src"):
            shutil.copytree(root / directory, repo / directory, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        shutil.copy2(root / "pyproject.toml", repo / "pyproject.toml")
        (repo / "notebooks").mkdir()
        kernel_dir = stage / "kernels" / "bankstress-guides"
        kernel_dir.mkdir(parents=True)
        (kernel_dir / "kernel.json").write_text(json.dumps({
            "argv": [sys.executable, "-Xfrozen_modules=off", "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Python 3 (research guides)", "language": "python",
        }), encoding="utf-8")
        kernel_specs = KernelSpecManager(kernel_dirs=[str(kernel_dir.parent)], ensure_native_kernel=False)
        env = {**os.environ, "PYTHONPATH": str(repo / "src"), "PYTHONNOUSERSITE": "1",
               "IPYTHONDIR": str(stage / "ipython"), "JUPYTER_CONFIG_DIR": str(stage / "jupyter"),
               "MPLCONFIGDIR": str(stage / "matplotlib")}
        working = repo if cwd == "root" else repo / "notebooks"
        for name in GUIDES:
            notebook = nbformat.read(root / "notebooks" / name, as_version=4)
            for cell in notebook.cells:
                if cell.cell_type == "code":
                    cell.outputs, cell.execution_count = [], None
            manager = KernelManager(kernel_name="bankstress-guides", kernel_spec_manager=kernel_specs)
            client = NotebookClient(notebook, km=manager, timeout=120, allow_errors=False,
                                    force_raise_errors=True, record_timing=False)
            # Supplying a manager lets us bind the kernel to this interpreter.
            # Its lifecycle is ours; nbclient otherwise leaves custom managers alive.
            try:
                client.execute(cwd=str(working), env=env)
            finally:
                if manager.has_kernel:
                    manager.shutdown_kernel(now=True)
                manager.cleanup_resources()
            if protected_hashes(repo) != before or protected_hashes(root) != before:
                raise RuntimeError(f"{name}: protected evidence changed during execution")
            for cell in notebook.cells:
                cell.metadata.pop("execution", None)
            notebook.metadata["kernelspec"] = {
                "display_name": "Python 3", "language": "python", "name": "python3",
            }
            executed.append((name, notebook))
            print(f"PASS {name} (fresh kernel; cwd={cwd})")
        if write:
            for name, notebook in executed:
                nbformat.write(notebook, root / "notebooks" / name)
            print("Saved all three executed notebooks; protected inputs unchanged.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwd", choices=("root", "notebooks"), default="root")
    parser.add_argument("--write", action="store_true", help="Save outputs only after all three notebooks pass")
    args = parser.parse_args()
    run_guides(Path(__file__).resolve().parents[1], cwd=args.cwd, write=args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
