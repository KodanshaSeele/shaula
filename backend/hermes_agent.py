"""
Módulo de compatibilidade: Redireciona o hermes_agent legado para o AntigravityAgent.
"""

from .antigravity_agent import AntigravityAgent, antigravity_agent

HermesAgent = AntigravityAgent
hermes_agent = antigravity_agent
