from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
PACKAGE_PATH = FRONTEND_ROOT / "package.json"
LOCKFILE_PATH = FRONTEND_ROOT / "package-lock.json"
STREAM_CONTRACT_TEST_PATH = FRONTEND_ROOT / "src" / "api" / "stream.contract.test.ts"
NPM_COMMAND = "npm.cmd" if sys.platform == "win32" else "npm"

RUNTIME_PINS = {
    "class-variance-authority": "0.7.1",
    "clsx": "2.1.1",
    "ky": "2.0.2",
    "lucide-react": "1.31.0",
    "radix-ui": "1.6.7",
    "react": "19.2.8",
    "react-dom": "19.2.8",
    "react-router-dom": "7.18.2",
    "tailwind-merge": "3.6.0",
    "zod": "4.4.3",
}

DEV_PINS = {
    "@axe-core/playwright": "4.13.0",
    "@biomejs/biome": "2.5.8",
    "@playwright/test": "1.62.1",
    "@tailwindcss/vite": "4.3.3",
    "@testing-library/jest-dom": "7.0.1",
    "@testing-library/react": "16.3.2",
    "@testing-library/user-event": "14.6.4",
    "@types/node": "24.13.3",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "@vitejs/plugin-react": "6.0.5",
    "@vitest/coverage-v8": "4.1.10",
    "axe-core": "4.13.0",
    "chrome-launcher": "1.2.1",
    "jsdom": "30.0.1",
    "lighthouse": "13.4.1",
    "msw": "2.15.0",
    "playwright-lighthouse": "4.0.0",
    "react-doctor": "0.9.12",
    "react-grab": "0.1.50",
    "react-scan": "0.5.7",
    "shadcn": "4.18.0",
    "tailwindcss": "4.3.3",
    "typescript": "7.0.2",
    "vite": "8.2.1",
    "vite-plugin-react-scan": "1.0.1",
    "vitest": "4.1.10",
}


def _package() -> dict[str, object]:
    assert PACKAGE_PATH.is_file(), "Stage 2 requires frontend/package.json"
    return json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))


def test_frontend_package_pins_toolchain_and_direct_dependencies() -> None:
    package = _package()

    assert package["packageManager"] == "npm@11.17.0"
    assert package["engines"] == {"node": "24.19.0", "npm": "11.17.0"}
    scripts = package["scripts"]
    assert isinstance(scripts, dict)
    required_scripts = {
        "typecheck",
        "lint",
        "test",
        "build",
        "test:e2e",
        "test:a11y",
        "test:perf",
        "doctor",
        "audit:prod",
    }
    assert required_scripts <= set(scripts)
    assert all(
        isinstance(scripts[name], str) and scripts[name] for name in required_scripts
    )
    assert package["dependencies"] == RUNTIME_PINS
    assert package["devDependencies"] == DEV_PINS


def test_frontend_lockfile_is_committed_for_the_exact_package_contract() -> None:
    package = _package()
    assert LOCKFILE_PATH.is_file(), "Stage 2 requires frontend/package-lock.json"

    lockfile = json.loads(LOCKFILE_PATH.read_text(encoding="utf-8"))
    root_package = lockfile["packages"][""]
    assert lockfile["lockfileVersion"] >= 3
    assert root_package["dependencies"] == package["dependencies"]
    assert root_package["devDependencies"] == package["devDependencies"]


def test_production_build_excludes_debug_tooling_and_source_maps() -> None:
    dist_root = FRONTEND_ROOT / "dist"
    assert dist_root.is_dir(), (
        "Stage 2 requires a built frontend/dist production bundle"
    )

    package = _package()
    runtime_dependencies = package["dependencies"]
    dev_dependencies = package["devDependencies"]
    assert isinstance(runtime_dependencies, dict)
    assert isinstance(dev_dependencies, dict)
    tooling = {"react-grab", "react-scan", "react-doctor"}
    assert tooling.isdisjoint(runtime_dependencies)
    assert tooling <= set(dev_dependencies)

    bundle = "\n".join(
        path.read_text(encoding="utf-8")
        for path in dist_root.rglob("*")
        if path.suffix in {".css", ".html", ".js"}
    )
    assert all(package_name not in bundle for package_name in tooling)
    assert not list(dist_root.rglob("*.map"))


def test_typed_public_sse_contract_has_no_result_event_or_automatic_retry() -> None:
    assert STREAM_CONTRACT_TEST_PATH.is_file(), (
        "Stage 2 requires an executable frontend SSE contract test"
    )
    package = _package()
    scripts = package["scripts"]
    assert isinstance(scripts, dict)
    assert "test" in scripts

    result = subprocess.run(
        [NPM_COMMAND, "run", "test", "--", "src/api/stream.contract.test.ts"],
        cwd=FRONTEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
