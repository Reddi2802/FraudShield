"""
network_intelligence_agent
Runs as a scheduled batch job (see scripts/network_graph_batch.py), NOT in the
synchronous per-transaction pipeline. Builds a co-occurrence graph across
card1/addr/id_ fields and writes a precomputed network-risk signal that
risk_synthesis_agent reads at inference time.
Implementation pending.
"""
