"""Parcel feature provider: reads the precomputed `parcel_features` document of one parcel and decision day.

The producer (an offline process outside this package) writes one JSON file per parcel and decision day; this module
only reads it. Nothing is computed and no network is used. The directory is `SMARTAGRI_PARCEL_FEATURES_DIR`; a file
is named `<parcel_id>__<YYYY-MM-DD>.json` (the decision day). The document is checked as a whole against the contract
(core/parcel_features.py): the schema, the parcel, the hash of the parcel geometry and every observation date against the
decision moment. A document that fails is rejected with the reasons, never partly used.

The interface is generic (`ParcelFeatureProvider`): another source (a service, a database) implements `get` and returns
the raw document, and `load` validates it the same way.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..core import parcel_features
from ..core.types import ParcelFeatures
from .base import ProviderUnavailable

SOURCE = "parcel feature provider (precomputed file)"
ENV_DIR = "SMARTAGRI_PARCEL_FEATURES_DIR"


class ParcelFeatureProvider:
    """Returns the raw `parcel_features` document for (parcel_id, as_of), or None when it has none."""

    def get(self, parcel_id: str, as_of: datetime) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class FileProvider(ParcelFeatureProvider):
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def path_for(self, parcel_id: str, as_of: datetime) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", parcel_id)
        return self.directory / ("%s__%s.json" % (safe, as_of.date().isoformat()))

    def get(self, parcel_id: str, as_of: datetime) -> Optional[Dict[str, Any]]:
        path = self.path_for(parcel_id, as_of)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderUnavailable("Datoteka pokazatelja parcele (%s) se ne može pročitati: %s." % (path.name, exc.__class__.__name__))


def configured() -> bool:
    return bool(os.environ.get(ENV_DIR))


def default_provider() -> Optional[ParcelFeatureProvider]:
    directory = os.environ.get(ENV_DIR)
    return FileProvider(Path(directory)) if directory else None


def load_document(parcel_id: str, geometry: Dict[str, Any], as_of: datetime,
                  provider: Optional[ParcelFeatureProvider] = None) -> Optional[Dict[str, Any]]:
    """The raw document of the parcel at as_of once it has passed the contract (schema, parcel, geometry hash, decision
    moment), None when the provider has none, and ProviderUnavailable (every reason in the message) when it has one that
    cannot be used. The raw document is what a profile stores: its hash is the hash the producer wrote."""
    provider = provider or default_provider()
    if provider is None:
        return None
    doc = provider.get(parcel_id, as_of)
    if doc is None:
        return None
    try:
        parcel_features.parse(doc, as_of=as_of, parcel_id=parcel_id, geometry=geometry)
    except parcel_features.ParcelFeaturesError as exc:
        raise ProviderUnavailable("Pokazatelji parcele su odbijeni: " + "; ".join(exc.errors))
    return doc


def load(parcel_id: str, geometry: Dict[str, Any], as_of: datetime,
         provider: Optional[ParcelFeatureProvider] = None) -> Optional[ParcelFeatures]:
    """`load_document`, parsed."""
    doc = load_document(parcel_id, geometry, as_of, provider)
    return None if doc is None else parcel_features.parse(doc, as_of=as_of, parcel_id=parcel_id, geometry=geometry)
