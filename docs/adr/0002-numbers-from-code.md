# 0002. Agronomic numbers come from code, never from a language model

- Status: Accepted
- Date: 2026-10-21

## Context

Language models produce plausible numbers that may be wrong. In irrigation and fertilization advice a wrong depth or
dose is a costly error, and it is hard to spot in fluent text.

## Decision

Every agronomic number in an answer is computed by a tool in `backend/src/smartagri/core/tools/` (ETc = Kc × ET0,
net need, gross depth = net / efficiency, application time, phenology, NDVI summary). Each tool returns its inputs,
output, formula and source (`ToolResult`), and is unit-tested (`tests/test_tools.py`). The template generator only
formats tool outputs. With a language model, γ rejects any number that does not appear in a tool output or in the
context (`core/grounding.py`, `unsupported_numbers`), and the answer falls back to the template
(`pipeline/generate.py`).

A quantity is shown only when the policy allows it and the parameters of the calculation have been reviewed
(`config/rules.yaml`, `irrigation.quantity_validated`).

## Consequences

- Each number can be traced to a formula, its inputs and a configuration hash.
- The number check is lexical: it compares numbers, not their meaning, and cannot catch a correct number used in a
  wrong sentence.
- While `quantity_validated` is `false`, no irrigation depth is stated in answers ([limitations.md](../limitations.md)).
