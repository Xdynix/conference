# Conference Management System

A Django application for managing academic conferences, covering the full lifecycle from
paper submission and peer review through decisions, registration, and payments.

## Prerequisites

- Python 3.14
- [uv](https://docs.astral.sh/uv/) (package manager)
- [just](https://github.com/casey/just) (task runner)

## Quick Start

```bash
just dev-setup    # install dependencies, pre-commit hooks, and dev certificates
just seed-dummy   # populate the database with sample data (optional)
just dev          # start the development application
```

The app will be available at `https://localhost:8000`.

Run `just --list` to see all available commands.

## Documentation

- **[WORKFLOWS.md](WORKFLOWS.md)** - User-facing workflows and state machines.
- **[AGENTS.md](AGENTS.md)** - Development guidelines, project structure, and coding
  conventions.
