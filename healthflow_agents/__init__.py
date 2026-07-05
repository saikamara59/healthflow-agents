"""HealthFlow's insurance-navigation Claude agents, standalone.

Agents are constructed with injected logging interfaces (see
healthflow_agents.core.logging); with no arguments they run standalone
with stdout defaults.
"""
from healthflow_agents.agents.comparison_agent import ComparisonAgent

__version__ = "0.1.0"

__all__ = [
    "ComparisonAgent",
]
