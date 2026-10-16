"""Usage source registry.

Adding a source means writing one module and adding one entry to `REGISTRY` —
never a branch on a provider id in shared code. See
docs/reference/provider-extension.md.

The registry holds classes, not instances. Providers take the shared scan cache,
which only exists once the daemon has opened it, so instantiating at import time
produced cacheless singletons that nothing used: the daemon named its two
providers by hand instead, and the registry silently stopped being the list that
mattered. `build()` is now the only way anything gets a provider.
"""

from __future__ import annotations

from .antigravity import AntigravityProvider
from .base import ScanningProvider, UsageProvider
from .claude import ClaudeProvider
from .codex import CodexProvider
from .gemini import GeminiProvider
from .copilot import CopilotProvider
from .cursor import CursorProvider
from .grok import GrokProvider
from .hermes import HermesProvider
from .kimi import KimiCodeProvider
from .kiro import KiroProvider
from .opencode import OpenCodeProvider
from .pi import OmpProvider, PiProvider

REGISTRY: list[type] = [
    ClaudeProvider,
    CodexProvider,
    GeminiProvider,
    PiProvider,
    OmpProvider,
    GrokProvider,
    OpenCodeProvider,
    HermesProvider,
    CopilotProvider,
    CursorProvider,
    KiroProvider,
    KimiCodeProvider,
    AntigravityProvider,
]


def build(cache=None, home=None, custom_roots=None) -> list[UsageProvider]:
    """Every registered provider, sharing one scan cache.

    `custom_roots` is a callable taking a provider id, not a dict: the daemon
    reloads its config in place, and a captured mapping would keep serving the
    settings as they were at process start.
    """
    return [cls(cache=cache, home=home, custom_roots=custom_roots) for cls in REGISTRY]


def registered_ids() -> list[str]:
    """Provider ids, for settings rows and registry-integrity tests."""
    return [cls.id for cls in REGISTRY]


__all__ = [
    "REGISTRY",
    "ScanningProvider",
    "UsageProvider",
    "build",
    "registered_ids",
    "ClaudeProvider",
    "CodexProvider",
    "GeminiProvider",
    "PiProvider",
    "OmpProvider",
    "GrokProvider",
    "OpenCodeProvider",
    "HermesProvider",
    "CopilotProvider",
    "CursorProvider",
    "KiroProvider",
    "KimiCodeProvider",
    "AntigravityProvider",
]
