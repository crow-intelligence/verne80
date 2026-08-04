# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-08-03

### Added

- `verne80.sources` — the Gutenberg #103 source record and its URL patterns.
- `verne80.normalize` — typography folding and whitespace collapse, the primitive every
  verbatim comparison in the project goes through.
- `verne80.chapters` — Gutenberg boilerplate stripping, column-0 heading anchoring, the
  37-chapter split, and `check_chapters`, which reports problems instead of guessing.
- `verne80.prompt` — the single copy of the extraction prompt template, plus rendering.
- `verne80.schema` — pydantic models for the per-chapter extraction JSON, with money null by
  default and transport-mode coercion that records what it changed.
- `verne80.extractions` — fence- and preamble-tolerant loading of Gemini's JSON output.
- `verne80.evidence` — the evidence-quote match ladder and near-miss reporting.
- `verne80.report` — the review queue, as JSON and as Markdown.
- `scripts/00_fetch.py`, `01_chapters.py`, `02_prompts.py`, `03_validate.py` — the four
  pipeline stages, communicating only through the filesystem.
