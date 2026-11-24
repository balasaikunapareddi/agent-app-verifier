"""agent-app-verifier: an agent-native app verification loop.

An LLM agent builds an app from a declarative spec, then drives it through
ten operations (tree, screenshot, tap, type, state, layout, logs, clock,
prefer, perf) — seeing it and running scripted tests until it passes.
"""

from .agent import AppVerifierAgent
from .driver import AppDriver
from .spec import AppSpec

__all__ = ["AppVerifierAgent", "AppDriver", "AppSpec"]
__version__ = "0.1.0"
