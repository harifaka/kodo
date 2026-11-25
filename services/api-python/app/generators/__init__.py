"""Stack generator plugin registry (Phase 4).

Importing this package registers every bundled plugin. Callers only depend on
:func:`app.generators.base.generate_files` / :func:`app.generators.base.get_plugin`.
"""

# Importing the modules performs the registration as a side effect.
from app.generators import csharp_wpf, nodejs, python_fastapi, spring_boot
from app.generators.base import (
    GeneratedFile,
    GeneratorConfig,
    GeneratorError,
    StackGeneratorPlugin,
    generate_files,
    get_plugin,
    language_for_path,
    register,
    registry,
)

__all__ = [
    "GeneratedFile",
    "GeneratorConfig",
    "GeneratorError",
    "StackGeneratorPlugin",
    "csharp_wpf",
    "generate_files",
    "get_plugin",
    "language_for_path",
    "nodejs",
    "python_fastapi",
    "register",
    "registry",
    "spring_boot",
]
