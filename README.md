# LLM-ABM Marketing Diffusion Simulator

A lightweight agent-based modeling project for simulating how a marketing post diffuses through a real social network.

The design goal is not a generic autonomous agent framework. The core is a reproducible ABM simulation engine where each social user agent makes a binary `engage / not engage` decision with an LLM-supported reasoning module.

## Core Modeling Contract

- **Agent**: social-media user with individual preference, history, and neighbor context.
- **Environment**: simulation scenario built on a real social network dataset.
- **Decision**: LLM-supported binary decision using three dimensions:
  - post content
  - individual preference
  - peer influence
- **Simulation**: multi-step post diffusion process over a graph.
- **Outputs**: reach, engagement rate, diffusion depth, spread speed, key influencers, and time-series diffusion records.

## Recommended Stack

- Python
- NetworkX for graph loading, neighbor queries, and network metrics
- A lightweight custom ABM kernel, with optional Mesa integration later
- Pydantic for typed simulation state and LLM output schema
- DuckDB or SQLite for decision cache and experiment records

## Architecture Notes

See `docs/architecture.md` and `docs/simulation-flow.md`.
