"""Questionnaire specifications: column codes, answer codes and scale membership."""

from __future__ import annotations

from spot_report.questionnaire.spec import (
    Question,
    QuestionKind,
    QuestionnaireSpec,
    Scale,
    Scoring,
    SpecError,
    Subscale,
    UnknownVersionError,
    available_versions,
    load_spec,
    spec_from_mapping,
)

__all__ = [
    "Question",
    "QuestionKind",
    "QuestionnaireSpec",
    "Scale",
    "Scoring",
    "SpecError",
    "Subscale",
    "UnknownVersionError",
    "available_versions",
    "load_spec",
    "spec_from_mapping",
]
