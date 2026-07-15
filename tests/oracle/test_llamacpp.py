"""Unit tests for LlamaCppOracle's import-time behavior.

The module must import cleanly without llama-cpp-python, and construction
without the dependency must fail with install guidance. Inference itself
is validated manually (no real models in the suite).
"""

import importlib.util

import pytest

llama_cpp_installed = importlib.util.find_spec("llama_cpp") is not None


def test_module_imports_without_dependency() -> None:
    import sanctum.oracle.llamacpp  # noqa: F401  (lazy import contract)


@pytest.mark.skipif(llama_cpp_installed, reason="llama-cpp-python is installed")
def test_construction_without_dependency_gives_install_guidance(tmp_path) -> None:
    from sanctum.oracle.llamacpp import LlamaCppOracle

    with pytest.raises(ImportError, match=r"sanctum-engine\[llamacpp\]"):
        LlamaCppOracle(model_path=tmp_path / "model.gguf")
