"""Persistence.

PostgreSQL with PostGIS and pgvector is the target database (DATABASE_URL). SQLite remains as a
zero-setup backend for unit tests and quick local runs. Both expose the same Store interface:
every record is a JSON document with a few real columns for keys, ordering and, on PostgreSQL,
the parcel geometry and the passage embeddings.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

log = logging.getLogger("agrovid.store")


class DatabaseUnavailable(Exception):
    """The database could not be reached or the connection broke (spec 052): the API answers 503, the pool
    reconnects on the next call."""

TABLES = {
    # table: extra key columns besides id, created_at, data
    "parcels": ["org_id"],
    "profiles": ["parcel_id", "org_id"],
    "conversations": ["parcel_id", "org_id"],
    "runs": ["conversation_id", "turn", "org_id"],
    "eval_items": ["batch_id", "scenario_id", "variant", "repeat"],
    "ratings": ["item_id", "rater"],
    # Accounts and teams (spec 011). Secrets (password hash, token hashes) live in `data`; the key
    # columns are the lookups. Session and token ids are sha256 hashes of the secret, never the secret.
    "users": ["email", "locale"],          # locale: spec 017, nullable
    "organizations": ["slug"],
    "memberships": ["user_id", "org_id"],
    "invites": ["token_hash", "org_id"],
    "email_tokens": ["token_hash", "user_id"],
    "sessions": ["user_id"],
    "ai_usage": ["org_id", "day"],
    # Activity log and traceability (spec 013). Soft delete (deleted_at in the document); the event table is
    # append-only (one row per create, update or delete, with the diff).
    "activities": ["org_id", "parcel_id", "kind", "date", "lot_id"],
    "activity_events": ["activity_id", "org_id"],
    # EUDR draft due-diligence statements (spec 014), each a snapshot of its parcels and lots.
    "eudr_statements": ["org_id"],
}
# Indexes added on top of the generic tables (both backends).
INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx ON users (email)",
    "CREATE UNIQUE INDEX IF NOT EXISTS organizations_slug_idx ON organizations (slug)",
    "CREATE UNIQUE INDEX IF NOT EXISTS memberships_user_org_idx ON memberships (user_id, org_id)",
    "CREATE INDEX IF NOT EXISTS memberships_org_idx ON memberships (org_id)",
    "CREATE INDEX IF NOT EXISTS invites_token_idx ON invites (token_hash)",
    "CREATE INDEX IF NOT EXISTS email_tokens_token_idx ON email_tokens (token_hash)",
    "CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS parcels_org_idx ON parcels (org_id)",
    "CREATE INDEX IF NOT EXISTS activities_parcel_idx ON activities (parcel_id, date)",
    "CREATE INDEX IF NOT EXISTS activities_org_idx ON activities (org_id, date)",
    "CREATE INDEX IF NOT EXISTS activities_lot_idx ON activities (org_id, lot_id)",
    "CREATE INDEX IF NOT EXISTS activity_events_activity_idx ON activity_events (activity_id)",
    "CREATE INDEX IF NOT EXISTS eudr_statements_org_idx ON eudr_statements (org_id)",
]
# Alerts and notifications (spec 018) and the worker's job lease table (shared by later product specs).
TABLES.update({
    "alert_rules": ["org_id", "parcel_id", "kind"],          # last evaluated state per (parcel, kind), for transitions
    "alert_prefs": ["user_id", "org_id"],
    "alerts": ["org_id", "parcel_id", "kind", "dedup_key", "status"],
    "notifications": ["org_id", "user_id", "alert_id", "channel", "status", "due_at"],
    "push_subscriptions": ["user_id", "org_id", "endpoint_hash"],
    "job_runs": ["job", "slot"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS alert_rules_parcel_kind_idx ON alert_rules (parcel_id, kind)",
    "CREATE UNIQUE INDEX IF NOT EXISTS alert_prefs_user_org_idx ON alert_prefs (user_id, org_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS alerts_org_dedup_idx ON alerts (org_id, dedup_key)",
    "CREATE INDEX IF NOT EXISTS alerts_org_created_idx ON alerts (org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS alerts_parcel_idx ON alerts (parcel_id, status)",
    "CREATE INDEX IF NOT EXISTS notifications_user_status_idx ON notifications (user_id, status)",
    "CREATE INDEX IF NOT EXISTS notifications_status_due_idx ON notifications (status, due_at)",
    "CREATE INDEX IF NOT EXISTS notifications_alert_idx ON notifications (alert_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS push_subscriptions_endpoint_idx ON push_subscriptions (endpoint_hash)",
    "CREATE UNIQUE INDEX IF NOT EXISTS job_runs_job_slot_idx ON job_runs (job, slot)",
]

# Soil-moisture sensors, ingest API keys and laboratory soil analyses (spec 020). measured_at is UTC text
# (2026-07-14T05:00:00Z), sortable on both backends; event tables are append-only; key secrets are sha256 only.
TABLES.update({
    "sensor_devices": ["org_id", "parcel_id"],
    "sensors": ["org_id", "device_id", "sensor_id"],
    "sensor_readings": ["org_id", "parcel_id", "sensor_id", "measured_at"],
    "sensor_imports": ["org_id", "parcel_id"],
    "api_keys": ["org_id", "key_id"],
    "api_key_events": ["org_id", "key_id"],
    "soil_analyses": ["org_id", "parcel_id", "sampled_on"],
    "soil_analysis_events": ["analysis_id", "org_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS sensor_devices_org_idx ON sensor_devices (org_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS sensors_org_sensor_idx ON sensors (org_id, sensor_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS sensor_readings_org_sensor_time_idx ON sensor_readings (org_id, sensor_id, measured_at)",
    "CREATE INDEX IF NOT EXISTS sensor_readings_parcel_time_idx ON sensor_readings (parcel_id, measured_at)",
    "CREATE INDEX IF NOT EXISTS sensor_imports_org_idx ON sensor_imports (org_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS api_keys_key_idx ON api_keys (key_id)",
    "CREATE INDEX IF NOT EXISTS api_key_events_key_idx ON api_key_events (key_id, created_at)",
    "CREATE INDEX IF NOT EXISTS soil_analyses_parcel_idx ON soil_analyses (parcel_id, sampled_on)",
    "CREATE INDEX IF NOT EXISTS soil_analysis_events_analysis_idx ON soil_analysis_events (analysis_id)",
]

# Costs, revenue and gross margin (spec 022). Money as decimal strings in the documents; soft delete; finance_events
# is append-only (Economics._event refuses an existing id). Overheads are cost_lines with parcel_id null.
TABLES.update({
    "price_list": ["org_id", "item_key"],
    "cost_lines": ["org_id", "parcel_id", "activity_id", "season"],
    "sales": ["org_id", "season", "lot_id"],
    "finance_events": ["org_id", "record_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS price_list_org_item_idx ON price_list (org_id, item_key)",
    "CREATE INDEX IF NOT EXISTS cost_lines_org_season_idx ON cost_lines (org_id, season)",
    "CREATE INDEX IF NOT EXISTS cost_lines_activity_idx ON cost_lines (activity_id)",
    "CREATE INDEX IF NOT EXISTS cost_lines_parcel_season_idx ON cost_lines (parcel_id, season)",
    "CREATE INDEX IF NOT EXISTS sales_org_season_idx ON sales (org_id, season)",
    "CREATE INDEX IF NOT EXISTS finance_events_record_idx ON finance_events (record_id)",
]

# Photo observations (spec 023). The image files live on the `media` volume (AGROVID_MEDIA_DIR), never in the database;
# `media` holds the metadata and the stored description, `media_events` is append-only (no image data).
# Uniqueness of (parcel_id, sha256) among non-deleted photos is enforced in code (api/media_service.py).
TABLES.update({
    "media": ["org_id", "parcel_id", "sha256", "kind"],
    "media_events": ["media_id", "org_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS media_parcel_idx ON media (parcel_id, created_at)",
    "CREATE INDEX IF NOT EXISTS media_org_idx ON media (org_id)",
    "CREATE INDEX IF NOT EXISTS media_parcel_sha_idx ON media (parcel_id, sha256)",
    "CREATE INDEX IF NOT EXISTS media_events_media_idx ON media_events (media_id)",
]

# Within-field NDVI zones and user-rated prescriptions (spec 021). Class arrays are zlib + base64 inside the document;
# a prescription keeps a snapshot of the parcel geometry and of the covered zone array, so it survives later changes.
TABLES.update({
    "zone_maps": ["org_id", "parcel_id"],
    "prescriptions": ["org_id", "parcel_id", "zone_map_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS zone_maps_org_parcel_idx ON zone_maps (org_id, parcel_id)",
    "CREATE INDEX IF NOT EXISTS prescriptions_org_parcel_idx ON prescriptions (org_id, parcel_id)",
    "CREATE INDEX IF NOT EXISTS prescriptions_zone_map_idx ON prescriptions (zone_map_id)",
]

# Offline clients (spec 025): stored responses of requests sent with an Idempotency-Key, per organisation, kept 24 h.
# id = sha256(org_id, key); expires_at is UTC text (2026-10-13T10:00:00Z), sortable on both backends. The document
# holds the request fingerprint, the state (pending|done) and the response; no request body is stored.
TABLES.update({
    "idempotency_keys": ["org_id", "idem_key", "expires_at"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS idempotency_keys_org_key_idx ON idempotency_keys (org_id, idem_key)",
    "CREATE INDEX IF NOT EXISTS idempotency_keys_expires_idx ON idempotency_keys (expires_at)",
]

# Advisor workspace (spec 024). advisor_links: consent records between an advisor organisation and a farm (at most
# one pending/active link per pair, enforced in code); advice_reviews: post-hoc human review next to a run (the run is
# never changed), one per (run, advisor organisation); advisor_events: append-only audit (refuses an existing id).
TABLES.update({
    "advisor_links": ["advisor_org_id", "farm_org_id", "status"],
    "advice_reviews": ["run_id", "farm_org_id", "advisor_org_id", "status"],
    "advisor_recommendations": ["advisor_org_id", "farm_org_id"],
    "advisor_events": ["advisor_org_id", "farm_org_id", "action"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS advisor_links_farm_idx ON advisor_links (farm_org_id, status)",
    "CREATE INDEX IF NOT EXISTS advisor_links_advisor_idx ON advisor_links (advisor_org_id, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS advice_reviews_run_advisor_idx ON advice_reviews (run_id, advisor_org_id)",
    "CREATE INDEX IF NOT EXISTS advice_reviews_farm_idx ON advice_reviews (farm_org_id, status)",
    "CREATE INDEX IF NOT EXISTS advisor_recommendations_farm_idx ON advisor_recommendations (farm_org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS advisor_events_farm_idx ON advisor_events (farm_org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS advisor_events_advisor_idx ON advisor_events (advisor_org_id, created_at)",
]

# Farms, field crops and per-field access (spec 027). A parcel belongs to exactly one farm of its organisation (key
# column parcels.farm_id, added by the column-adding path below); field_crops holds one row per planting (several per
# season), field_crop_events is append-only; field_access holds per-parcel grants of members whose membership document
# has field_scope "listed" (workers and inspectors only). Unique farm names per organisation are checked in code.
TABLES["parcels"] = TABLES["parcels"] + ["farm_id"]
TABLES.update({
    "farms": ["org_id", "name"],
    "field_crops": ["org_id", "parcel_id", "season", "crop", "status"],
    "field_crop_events": ["field_crop_id", "org_id"],
    "field_access": ["org_id", "user_id", "parcel_id"],
    "field_access_events": ["org_id", "user_id"],          # append-only audit of grant changes
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS parcels_org_farm_idx ON parcels (org_id, farm_id)",
    "CREATE INDEX IF NOT EXISTS farms_org_idx ON farms (org_id)",
    "CREATE INDEX IF NOT EXISTS field_crops_parcel_season_idx ON field_crops (parcel_id, season)",
    "CREATE INDEX IF NOT EXISTS field_crops_org_season_idx ON field_crops (org_id, season)",
    "CREATE INDEX IF NOT EXISTS field_crop_events_crop_idx ON field_crop_events (field_crop_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS field_access_org_user_parcel_idx ON field_access (org_id, user_id, parcel_id)",
    "CREATE INDEX IF NOT EXISTS field_access_parcel_idx ON field_access (parcel_id)",
]


# Atlas and symptom key (spec 030). Instance-wide tables (no org_id): atlas_entries keeps the working copy of an entry
# and, in `live`, the last published snapshot shown to farmers (key column visible = "1"); atlas_events is append-only;
# instance_roles holds instance-level roles (atlas_edit, atlas_review) set by the operator CLI.
TABLES.update({
    "atlas_entries": ["kind", "status", "eppo_code", "slug", "search_text", "visible"],
    "atlas_images": ["entry_id", "licence"],
    "atlas_imports": ["status", "created_by"],
    "atlas_events": ["entry_id"],
    "instance_roles": ["user_id"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS atlas_entries_slug_idx ON atlas_entries (slug)",
    "CREATE INDEX IF NOT EXISTS atlas_entries_status_kind_idx ON atlas_entries (status, kind)",
    "CREATE INDEX IF NOT EXISTS atlas_entries_visible_idx ON atlas_entries (visible)",
    "CREATE INDEX IF NOT EXISTS atlas_entries_eppo_idx ON atlas_entries (eppo_code)",
    "CREATE INDEX IF NOT EXISTS atlas_images_entry_idx ON atlas_images (entry_id)",
    "CREATE INDEX IF NOT EXISTS atlas_imports_created_idx ON atlas_imports (created_at)",
    "CREATE INDEX IF NOT EXISTS atlas_events_entry_idx ON atlas_events (entry_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS instance_roles_user_idx ON instance_roles (user_id)",
]


# End-of-season production surveys (spec 029). One survey per field crop (per harvest year for perennial crops; unique
# (field_crop_id, season), checked in code and by the index); season is text on both backends (the document keeps the
# integer). season_survey_events is append-only (insert_new) with a snapshot per action; research_consents is
# append-only too: every grant and every revocation is a new row, the newest row of an organisation is its state.
TABLES.update({
    "season_surveys": ["org_id", "parcel_id", "field_crop_id", "season", "crop", "status"],
    "season_survey_events": ["survey_id", "org_id"],
    "research_consents": ["org_id", "status"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS season_surveys_crop_season_idx ON season_surveys (field_crop_id, season)",
    "CREATE INDEX IF NOT EXISTS season_surveys_org_season_idx ON season_surveys (org_id, season)",
    "CREATE INDEX IF NOT EXISTS season_surveys_parcel_idx ON season_surveys (parcel_id)",
    "CREATE INDEX IF NOT EXISTS season_survey_events_survey_idx ON season_survey_events (survey_id)",
    "CREATE INDEX IF NOT EXISTS research_consents_org_idx ON research_consents (org_id)",
]


# Public API v1, personal access tokens and OAuth2 (spec 031). Secrets are never stored: api_tokens keeps sha256 of the
# whole personal token, oauth_codes/oauth_tokens are looked up by sha256 of the code or token. The event tables are
# append-only audit (usage is one summary row per token and day). Expired codes and tokens are purged by `oauth_purge`.
TABLES.update({
    "api_tokens": ["org_id", "user_id", "key_id"],
    "api_token_events": ["org_id", "key_id"],
    "oauth_clients": ["client_id"],
    "oauth_codes": ["code_hash", "client_id", "expires_at"],
    "oauth_grants": ["org_id", "user_id", "client_id", "status"],
    "oauth_tokens": ["token_hash", "grant_id", "kind", "family_id", "expires_at"],
    "oauth_events": ["org_id", "grant_id"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS api_tokens_key_idx ON api_tokens (key_id)",
    "CREATE INDEX IF NOT EXISTS api_tokens_user_idx ON api_tokens (user_id, org_id)",
    "CREATE INDEX IF NOT EXISTS api_token_events_org_idx ON api_token_events (org_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS oauth_clients_client_idx ON oauth_clients (client_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS oauth_codes_hash_idx ON oauth_codes (code_hash)",
    "CREATE INDEX IF NOT EXISTS oauth_grants_org_idx ON oauth_grants (org_id)",
    "CREATE INDEX IF NOT EXISTS oauth_grants_user_idx ON oauth_grants (user_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS oauth_tokens_hash_idx ON oauth_tokens (token_hash)",
    "CREATE INDEX IF NOT EXISTS oauth_tokens_family_idx ON oauth_tokens (family_id)",
    "CREATE INDEX IF NOT EXISTS oauth_tokens_grant_idx ON oauth_tokens (grant_id)",
    "CREATE INDEX IF NOT EXISTS oauth_events_org_idx ON oauth_events (org_id, created_at)",
]


# Scouting surveys (spec 028). One row per survey (document: population samples, observation rows, review);
# scouting_events is append-only (diffs without image data, export audit). client_key (offline outbox, spec 025) is
# unique per organisation where set. Parcel deletion removes both (Scouting.forget_parcel hook).
TABLES.update({
    "scouting_surveys": ["org_id", "parcel_id", "field_crop_id", "observed_on", "status", "user_id", "client_key"],
    "scouting_events": ["survey_id", "org_id", "parcel_id"],
})

# Shared rate-limit counters (spec 052, accounts/ratelimit.StoreRateLimiter): one row per (key, fixed window), the
# count `n` in the document, incremented atomically; expires_at is UTC text, purged opportunistically.
TABLES.update({
    "rate_counters": ["key", "expires_at"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS scouting_surveys_parcel_idx ON scouting_surveys (parcel_id, observed_on)",
    "CREATE INDEX IF NOT EXISTS scouting_surveys_org_idx ON scouting_surveys (org_id, observed_on)",
    "CREATE UNIQUE INDEX IF NOT EXISTS scouting_surveys_client_key_idx ON scouting_surveys (org_id, client_key) "
    "WHERE client_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS scouting_events_survey_idx ON scouting_events (survey_id)",
]
INDEXES += ["CREATE INDEX IF NOT EXISTS rate_counters_expires_idx ON rate_counters (expires_at)"]

# Parcel jurisdiction (spec 037 FR-003; used by the advice scope of spec 038): country_code (ISO 3166-1 alpha-2, XK,
# ZZ = unknown) is a key column for per-country queries; subdivision, origin, time zone and climate class live in the
# document. Added by the additive schema sync; existing rows are back-filled by migration 0002 (smartagri.migrate).
TABLES["parcels"] = TABLES["parcels"] + ["country_code"]
INDEXES += ["CREATE INDEX IF NOT EXISTS parcels_country_idx ON parcels (country_code)"]

# Agronomy analyses and reference datasets (spec 032). `analyses` are per organisation (saved assumptions, cached results,
# inputs hash; soft-deleted with deleted_at), `analysis_events` is append-only; `reference_datasets` is instance-wide
# (no org_id; visible = "1" when a published snapshot exists), `reference_events` append-only. Created by migration
# 0003 (smartagri.migrate); no back-fill.
TABLES.update({
    "analyses": ["org_id", "kind", "season", "crop", "parcel_id"],
    "analysis_events": ["analysis_id", "org_id"],
    "reference_datasets": ["slug", "crop", "variable", "status", "visible"],
    "reference_events": ["dataset_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS analyses_org_season_idx ON analyses (org_id, season)",
    "CREATE INDEX IF NOT EXISTS analysis_events_analysis_idx ON analysis_events (analysis_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS reference_datasets_slug_idx ON reference_datasets (slug)",
    "CREATE INDEX IF NOT EXISTS reference_datasets_crop_var_idx ON reference_datasets (crop, variable, status)",
    "CREATE INDEX IF NOT EXISTS reference_events_dataset_idx ON reference_events (dataset_id)",
]

# Hourly weather, weather stations (spec 035) and disease/pest risk models (spec 034). The time series themselves
# (weather_hourly, station_observations) are typed tables with monthly partitions on PostgreSQL, created by migration
# 0005 through weather/store.py; the tables here are documents: snapshots of the series used by a risk run
# (id = sha256 of the rows), the "Vreme i rizici" view interest per parcel (id = parcel id), stations, assignments
# (history kept), write-only encrypted vendor credentials, station audit events (append-only), risk runs (run_key =
# hash of model, version, parameters, settings, snapshot and as_of), per-parcel model settings with append-only events,
# and instance-level sign-offs of model versions.
TABLES.update({
    "weather_snapshots": ["parcel_id"],
    "weather_interest": ["parcel_id", "org_id"],
    "weather_stations": ["org_id", "status", "public_id"],
    "station_assignments": ["org_id", "parcel_id", "station_id"],
    "station_credentials": ["org_id", "station_id"],
    "station_events": ["org_id", "station_id"],
    "risk_runs": ["org_id", "parcel_id", "model_id", "run_key"],
    "risk_model_settings": ["org_id", "parcel_id", "model_id"],
    "risk_model_setting_events": ["org_id", "parcel_id", "model_id"],
    "risk_model_signoffs": ["model_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS weather_snapshots_parcel_idx ON weather_snapshots (parcel_id)",
    "CREATE INDEX IF NOT EXISTS weather_interest_org_idx ON weather_interest (org_id)",
    "CREATE INDEX IF NOT EXISTS weather_stations_org_idx ON weather_stations (org_id)",
    "CREATE INDEX IF NOT EXISTS weather_stations_public_idx ON weather_stations (public_id)",
    "CREATE INDEX IF NOT EXISTS station_assignments_parcel_idx ON station_assignments (parcel_id)",
    "CREATE INDEX IF NOT EXISTS station_assignments_station_idx ON station_assignments (station_id)",
    "CREATE INDEX IF NOT EXISTS station_credentials_station_idx ON station_credentials (station_id)",
    "CREATE INDEX IF NOT EXISTS station_events_station_idx ON station_events (station_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS risk_runs_key_idx ON risk_runs (run_key)",
    "CREATE INDEX IF NOT EXISTS risk_runs_parcel_model_idx ON risk_runs (parcel_id, model_id, created_at)",
    "CREATE INDEX IF NOT EXISTS risk_model_settings_parcel_idx ON risk_model_settings (parcel_id, model_id)",
    "CREATE INDEX IF NOT EXISTS risk_model_setting_events_idx ON risk_model_setting_events (parcel_id, model_id)",
    "CREATE INDEX IF NOT EXISTS risk_model_signoffs_model_idx ON risk_model_signoffs (model_id)",
]

# Cadastral import (spec 048), index layers and validation records (spec 049), spatial tools (spec 050). Additive
# document tables created by migration 0006 (smartagri.migrate); no back-fill. cadastre_cache holds only normalised,
# whitelisted parcels (never raw source responses, spec 048 FR-003); cadastre_job_claims makes a batch run single-process.
TABLES.update({
    "cadastre_jobs": ["org_id", "connector", "status"],
    "cadastre_job_items": ["job_id", "org_id", "idem_key", "status"],
    "cadastre_job_claims": ["job_id"],
    "cadastre_cache": ["connector", "ref_hash"],
    "layer_rasters": ["org_id", "parcel_id", "layer_id", "date", "geometry_hash"],
    "validation_samples": ["org_id", "parcel_id", "sampled_on"],
    "feature_layers": ["org_id", "kind"],
    "spatial_results": ["org_id", "parcel_id", "farm_id", "kind"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS cadastre_jobs_org_idx ON cadastre_jobs (org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS cadastre_job_items_job_idx ON cadastre_job_items (job_id, status)",
    "CREATE INDEX IF NOT EXISTS cadastre_job_items_org_key_idx ON cadastre_job_items (org_id, idem_key)",
    "CREATE UNIQUE INDEX IF NOT EXISTS cadastre_cache_key_idx ON cadastre_cache (connector, ref_hash)",
    "CREATE INDEX IF NOT EXISTS layer_rasters_parcel_idx ON layer_rasters (parcel_id, layer_id, date)",
    "CREATE INDEX IF NOT EXISTS validation_samples_org_idx ON validation_samples (org_id, sampled_on)",
    "CREATE INDEX IF NOT EXISTS feature_layers_org_idx ON feature_layers (org_id)",
    "CREATE INDEX IF NOT EXISTS spatial_results_parcel_idx ON spatial_results (org_id, parcel_id, kind)",
]

# Plans, entitlements and billing (spec 058). Additive document tables created by migration 0007; no back-fill.
# billing_events is the raw webhook log (payload hash + redacted JSON) whose unique (provider, event_id) makes webhook
# processing idempotent; entitlement_events is append-only (audit of overrides, band changes, subscription changes);
# usage_counters hold monthly meters (id = org:metric:period, atomic Store.increment). No card data anywhere.
TABLES.update({
    "subscriptions": ["org_id", "provider", "provider_subscription_id", "status"],
    "billing_profiles": ["org_id"],
    "billing_events": ["provider", "event_id", "org_id"],
    "invoices_mirror": ["org_id", "provider", "provider_invoice_id"],
    "entitlement_overrides": ["org_id", "expires_at"],
    "entitlement_events": ["org_id", "kind"],
    "usage_counters": ["org_id", "metric", "period_key"],
    "active_parcel_selection": ["org_id", "parcel_id"],
    "billing_coupons": ["code"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS subscriptions_org_idx ON subscriptions (org_id)",
    "CREATE INDEX IF NOT EXISTS subscriptions_provider_idx ON subscriptions (provider, provider_subscription_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS billing_events_provider_event_idx ON billing_events (provider, event_id)",
    "CREATE INDEX IF NOT EXISTS invoices_mirror_org_idx ON invoices_mirror (org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS entitlement_overrides_org_idx ON entitlement_overrides (org_id)",
    "CREATE INDEX IF NOT EXISTS entitlement_events_org_idx ON entitlement_events (org_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS usage_counters_key_idx ON usage_counters (org_id, metric, period_key)",
    "CREATE INDEX IF NOT EXISTS active_parcel_selection_org_idx ON active_parcel_selection (org_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS billing_coupons_code_idx ON billing_coupons (code)",
]

# Custom crops, "Druga kultura" (spec 059). Additive document table created by migration 0008; no back-fill. A record is
# never removed (archived_at in the document); parcels keep a snapshot of the custom crop they use.
TABLES.update({
    "custom_crops": ["org_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS custom_crops_org_idx ON custom_crops (org_id)",
]

# Tasks for workers (spec 044) and input inventory (spec 045). Additive document tables created by migration 0009; no
# back-fill. task_events and inv_events are append-only (insert_new); nothing is ever deleted: tasks are cancelled,
# products and locations archived, movements voided (voided_at + reason in the document).
TABLES.update({
    "tasks": ["org_id", "parcel_id", "assignee_id", "status", "due_date"],
    "task_events": ["task_id", "org_id"],
    "inv_products": ["org_id", "category"],
    "inv_locations": ["org_id"],
    "inv_lots": ["org_id", "product_id"],
    "inv_movements": ["org_id", "product_id", "lot_id", "activity_id", "kind", "date"],
    "inv_events": ["org_id", "record_id"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS tasks_org_status_idx ON tasks (org_id, status)",
    "CREATE INDEX IF NOT EXISTS tasks_assignee_idx ON tasks (assignee_id, status)",
    "CREATE INDEX IF NOT EXISTS tasks_parcel_idx ON tasks (parcel_id)",
    "CREATE INDEX IF NOT EXISTS task_events_task_idx ON task_events (task_id)",
    "CREATE INDEX IF NOT EXISTS inv_products_org_idx ON inv_products (org_id)",
    "CREATE INDEX IF NOT EXISTS inv_locations_org_idx ON inv_locations (org_id)",
    "CREATE INDEX IF NOT EXISTS inv_lots_product_idx ON inv_lots (product_id)",
    "CREATE INDEX IF NOT EXISTS inv_movements_org_date_idx ON inv_movements (org_id, date)",
    "CREATE INDEX IF NOT EXISTS inv_movements_product_idx ON inv_movements (product_id)",
    "CREATE INDEX IF NOT EXISTS inv_movements_activity_idx ON inv_movements (activity_id)",
    "CREATE INDEX IF NOT EXISTS inv_events_record_idx ON inv_events (record_id)",
]


# Satellite imagery browser (spec 040). Additive document tables created by migration 0010; no back-fill. imagery_scenes
# keeps the scene catalogue rows (cloud, shadow, snow and valid shares per parcel, date and geometry) so the list
# survives a provider outage; imagery_rgb holds true-colour images (uint8 RGB + SCL validity mask) on the parcel grid.
# Spec 041 (radar, rainfall card) stores nothing: radar is live, the card is computed from the spec 035 series.
TABLES.update({
    "imagery_scenes": ["org_id", "parcel_id", "date", "geometry_hash"],
    "imagery_rgb": ["org_id", "parcel_id", "date", "geometry_hash"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS imagery_scenes_parcel_idx ON imagery_scenes (parcel_id, date)",
    "CREATE INDEX IF NOT EXISTS imagery_rgb_parcel_idx ON imagery_rgb (parcel_id, date)",
]

# Plant-protection guidance from a curated national registry (spec 051). Instance-wide registry tables keyed by country
# (never per organisation), created by migration 0011; no back-fill. Rows of an activated import are immutable (refused
# in ppp.registry); ppp_import_events and ppp_guidance_events are append-only (insert_new; triggers refuse UPDATE and
# DELETE, created by migration 0011). ppp_guidance keeps each shown guidance object for re-validation at render time.
TABLES.update({
    "ppp_sources": ["country"],
    "ppp_imports": ["country", "status"],
    "ppp_products": ["import_id", "country", "registration_no"],
    "ppp_uses": ["import_id", "product_id"],
    "ppp_groups": ["import_id", "kind"],
    "ppp_import_events": ["import_id"],
    "ppp_eu_substances": ["name_key", "cas"],
    "ppp_merge_decisions": ["pair_key"],
    "ppp_proposals": ["country", "catalogue_key", "status"],
    "ppp_guidance": ["org_id", "parcel_id"],
    "ppp_guidance_events": ["org_id", "parcel_id", "surface"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS ppp_imports_country_idx ON ppp_imports (country, status)",
    "CREATE INDEX IF NOT EXISTS ppp_products_import_idx ON ppp_products (import_id)",
    "CREATE INDEX IF NOT EXISTS ppp_uses_import_idx ON ppp_uses (import_id)",
    "CREATE INDEX IF NOT EXISTS ppp_groups_import_idx ON ppp_groups (import_id)",
    "CREATE INDEX IF NOT EXISTS ppp_import_events_import_idx ON ppp_import_events (import_id)",
    "CREATE INDEX IF NOT EXISTS ppp_eu_substances_name_idx ON ppp_eu_substances (name_key)",
    "CREATE INDEX IF NOT EXISTS ppp_proposals_country_idx ON ppp_proposals (country, status)",
    "CREATE INDEX IF NOT EXISTS ppp_guidance_org_idx ON ppp_guidance (org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ppp_guidance_events_org_idx ON ppp_guidance_events (org_id, created_at)",
]


# Machinery data import (spec 043) and boundary suggestions (spec 046). Additive document tables created by migration
# 0012; no back-fill. machinery_points holds the parsed point columns of a dataset (zlib + base64, one row per dataset)
# so a dataset can be re-cleaned for another parcel without the upload; raw uploads are not stored (hash and size only).
# Nothing is deleted: an import is discarded by status; boundary_suggestions keeps each suggestion that was shown.
TABLES.update({
    "machinery_imports": ["org_id", "status"],
    "machinery_datasets": ["org_id", "import_id", "parcel_id", "kind"],
    "machinery_points": ["dataset_id", "org_id"],
    "boundary_suggestions": ["org_id", "status"],
})
INDEXES += [
    "CREATE INDEX IF NOT EXISTS machinery_imports_org_idx ON machinery_imports (org_id, created_at)",
    "CREATE INDEX IF NOT EXISTS machinery_datasets_import_idx ON machinery_datasets (import_id)",
    "CREATE INDEX IF NOT EXISTS machinery_datasets_parcel_idx ON machinery_datasets (parcel_id)",
    "CREATE INDEX IF NOT EXISTS boundary_suggestions_org_idx ON boundary_suggestions (org_id, created_at)",
]


# Messaging channels (spec 060). Additive document tables created by migration 0013; no back-fill. messaging_links binds
# one channel address (chat id or phone number, stored once to be able to send, looked up by sha256) to one member of one
# organisation, with the recorded consent; messaging_codes holds one-time link codes (sha256 only); messaging_log is the
# delivery log (no message text, no address); messaging_inbound deduplicates provider retries (purged after 7 days);
# messaging_counters holds rate-limit windows (atomic Store.increment).
TABLES.update({
    "messaging_links": ["user_id", "org_id", "channel", "address_hash", "status"],
    "messaging_codes": ["user_id", "org_id", "code_hash", "token_hash", "expires_at"],
    "messaging_log": ["org_id", "user_id", "link_id", "channel", "provider_message_id", "day"],
    "messaging_inbound": ["channel", "received_on"],
    "messaging_counters": ["key"],
})
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS messaging_links_address_idx ON messaging_links (channel, address_hash)",
    "CREATE INDEX IF NOT EXISTS messaging_links_user_idx ON messaging_links (user_id, org_id)",
    "CREATE INDEX IF NOT EXISTS messaging_codes_code_idx ON messaging_codes (code_hash)",
    "CREATE INDEX IF NOT EXISTS messaging_codes_token_idx ON messaging_codes (token_hash)",
    "CREATE INDEX IF NOT EXISTS messaging_log_user_idx ON messaging_log (user_id, org_id)",
    "CREATE INDEX IF NOT EXISTS messaging_log_provider_idx ON messaging_log (channel, provider_message_id)",
    "CREATE INDEX IF NOT EXISTS messaging_log_day_idx ON messaging_log (day)",
    "CREATE INDEX IF NOT EXISTS messaging_inbound_day_idx ON messaging_inbound (received_on)",
]

# Optional accounts of the research web app (research_api/auth.py; off by default, SMARTAGRI_ACCOUNTS=optional).
# Separate from the product's users/sessions tables: a research database never mixes the two. Secrets are never
# stored: core_sessions and core_tokens use sha256 of the secret as id; the password hash lives in the document.
# core_owners maps a parcel id (= row id) to its owner: "u:<user id>" or "b:<sha256 of an anonymous browser token>".
# Additive document tables created by migration 0014; no back-fill (parcels created before stay unowned).
TABLES.update({
    "core_users": ["email"],
    "core_sessions": ["user_id", "expires_at"],
    "core_tokens": ["user_id", "purpose", "expires_at"],
    "core_owners": ["owner", "kind"],
})
# Anonymous work is temporary: touched_at (UTC text, sortable) is the last activity of an anonymous browser's parcel;
# research_api/auth.py purges anonymous parcels idle longer than SMARTAGRI_ANON_TTL_HOURS. Additive key column (schema
# sync); account-owned rows do not use it.
TABLES["core_owners"] = TABLES["core_owners"] + ["touched_at"]
INDEXES += [
    "CREATE UNIQUE INDEX IF NOT EXISTS core_users_email_idx ON core_users (email)",
    "CREATE INDEX IF NOT EXISTS core_sessions_user_idx ON core_sessions (user_id)",
    "CREATE INDEX IF NOT EXISTS core_tokens_user_idx ON core_tokens (user_id, purpose)",
    "CREATE INDEX IF NOT EXISTS core_owners_owner_idx ON core_owners (owner, kind)",
    "CREATE INDEX IF NOT EXISTS core_owners_touched_idx ON core_owners (touched_at)",
]


def _typed_schema(backend: str) -> List[str]:
    """Typed time-series tables of spec 035 (weather_hourly, station_observations; monthly partitions on PostgreSQL),
    part of the idempotent schema so the repeatable schema sync and migration 0005 create the same thing."""
    from .weather.store import schema_statements
    return schema_statements(backend)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    """Backend-independent operations. Subclasses provide _exec, _rows and the schema."""

    backend = "abstract"
    ph = "?"                      # SQL parameter placeholder

    # ------------------------------------------------------------ to be provided by a backend
    def _exec(self, sql: str, args: Sequence[Any] = ()) -> None:
        raise NotImplementedError

    def _rows(self, sql: str, args: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _json(self, obj: Any) -> Any:
        return json.dumps(obj, ensure_ascii=False)

    @staticmethod
    def _load(value: Any) -> Any:
        return json.loads(value) if isinstance(value, (str, bytes)) else value

    def _after_put(self, table: str, obj: Dict[str, Any]) -> None:
        pass

    # ------------------------------------------------------------ transactions and health (spec 052)
    @contextlib.contextmanager
    def transaction(self) -> Iterator["Store"]:
        """All statements of the block commit together or not at all (nested blocks: savepoints on PostgreSQL,
        part of the outer transaction on SQLite). Backends override it; the base class runs the block as is."""
        yield self

    def ping(self, timeout_s: float = 1.0) -> Dict[str, Any]:
        """{ok, latency_ms, error}: a cheap `SELECT 1` bounded by `timeout_s` (health checks; spec 052)."""
        import concurrent.futures
        started = time.monotonic()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self._rows, "SELECT 1 AS ok")
            future.result(timeout=timeout_s)
            return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 1), "error": None}
        except concurrent.futures.TimeoutError:
            return {"ok": False, "latency_ms": None, "error": "timeout"}
        except Exception as exc:                     # any driver error means "not ready"
            return {"ok": False, "latency_ms": None, "error": exc.__class__.__name__}
        finally:
            pool.shutdown(wait=False)

    @contextlib.contextmanager
    def migration_lock(self) -> Iterator[None]:
        """Mutual exclusion of migration runs (PostgreSQL: advisory lock; SQLite: the store lock)."""
        yield

    def sync_schema(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    # ------------------------------------------------------------ atomic counters and batch reads (spec 052)
    def increment(self, table: str, id_: str, doc: Dict[str, Any], field: str = "n", by: int = 1) -> int:
        """Atomically add `by` to the integer `field` of document `id_` (created from `doc` with field = by when
        missing) and return the new value: one INSERT ... ON CONFLICT DO UPDATE ... RETURNING statement, so
        concurrent requests and several processes never lose an increment (AI quota, rate limits)."""
        if not field.isidentifier():
            raise ValueError("bad field %r" % field)
        obj = dict(doc, id=id_)
        obj.setdefault("created_at", now_iso())
        obj[field] = by
        cols = ["id", "created_at", "data"] + TABLES[table]
        vals = [obj["id"], obj["created_at"], self._json(obj)] + [obj.get(c) for c in TABLES[table]]
        if self.backend == "postgresql":
            upd = ("data = jsonb_set(%s.data, '{%s}', to_jsonb(COALESCE((%s.data->>'%s')::bigint, 0) + %d))"
                   % (table, field, table, field, int(by)))
            ret = "(data->>'%s')::bigint AS n" % field
        else:
            upd = ("data = json_set(%s.data, '$.%s', COALESCE(json_extract(%s.data, '$.%s'), 0) + %d)"
                   % (table, field, table, field, int(by)))
            ret = "json_extract(data, '$.%s') AS n" % field
        sql = "INSERT INTO %s (%s) VALUES (%s) ON CONFLICT (id) DO UPDATE SET %s RETURNING %s" % (
            table, ", ".join(cols), ", ".join("?" * len(cols)), upd, ret)
        with self.transaction():                     # SQLite: RETURNING rows are read before the commit
            rows = self._rows(self._q(sql), vals)
        return int(rows[0]["n"])

    def find_in(self, table: str, column: str, values: Sequence[Any], order: str = "seq") -> List[Dict[str, Any]]:
        """Every document whose key column `column` is one of `values` (one statement; batch loaders, PERF-1)."""
        if column not in set(TABLES[table]) | {"id"}:
            raise ValueError("unknown column %s for %s" % (column, table))
        values = list(dict.fromkeys(values))
        out: List[Dict[str, Any]] = []
        for i in range(0, len(values), 500):
            chunk = values[i:i + 500]
            out += self._list(table, "%s IN (%s)" % (column, ", ".join("?" * len(chunk))), chunk, order)
        return out

    # Per-thread read cache for list views (spec 052, PERF-1): inside `prefetch(parcel_ids)`, find(table,
    # parcel_id=x) for these tables, latest_profile(x) and has_parcel_rows("sensor_readings", x) are answered from a
    # few batch queries instead of one statement each per parcel. Same queries, same order, copies of the documents.
    PREFETCH_TABLES = ("activities", "scouting_surveys", "soil_analyses")

    def _prefetched(self) -> Optional[Dict[str, Any]]:
        local = self.__dict__.get("_local")
        return getattr(local, "prefetch", None) if local is not None else None

    @contextlib.contextmanager
    def prefetch(self, parcel_ids: Sequence[str]) -> Iterator[None]:
        local = self.__dict__.get("_local")
        if local is None or getattr(local, "prefetch", None) is not None or not parcel_ids:
            yield                                    # no thread-local slot, nested, or nothing to load
            return
        ids = list(dict.fromkeys(parcel_ids))
        found: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
        for table in self.PREFETCH_TABLES:
            groups: Dict[str, List[Dict[str, Any]]] = {pid: [] for pid in ids}
            for doc in self.find_in(table, "parcel_id", ids):
                groups.setdefault(doc.get("parcel_id"), []).append(doc)
            found[table] = groups
        readings = set()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            rows = self._rows(self._q("SELECT DISTINCT parcel_id FROM sensor_readings WHERE parcel_id IN (%s)"
                                      % ", ".join("?" * len(chunk))), chunk)
            readings |= {r["parcel_id"] for r in rows}
        local.prefetch = {"ids": set(ids), "find": found, "profiles": self.latest_profiles(ids),
                          "rows": {"sensor_readings": readings}}
        try:
            yield
        finally:
            local.prefetch = None

    def has_parcel_rows(self, table: str, parcel_id: str) -> bool:
        """True when `table` has a row of the parcel (prefetched in list views)."""
        cache = self._prefetched()
        if cache is not None and parcel_id in cache["ids"] and table in cache["rows"]:
            return parcel_id in cache["rows"][table]
        if "parcel_id" not in TABLES[table]:
            raise ValueError("%s has no parcel_id" % table)
        return bool(self._rows(self._q("SELECT 1 AS x FROM %s WHERE parcel_id = ? LIMIT 1" % table), (parcel_id,)))

    def latest_profiles(self, parcel_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """{parcel_id: newest profile} for many parcels in one statement (same choice as latest_profile)."""
        ids = list(dict.fromkeys(parcel_ids))
        out: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ", ".join("?" * len(chunk))
            sql = ("SELECT data FROM profiles WHERE seq IN (SELECT max(seq) FROM profiles WHERE parcel_id IN (%s) "
                   "GROUP BY parcel_id)" % marks)
            for r in self._rows(self._q(sql), chunk):
                doc = self._load(r["data"])
                out[doc["parcel_id"]] = doc
        return out

    # ------------------------------------------------------------ generic helpers
    def _q(self, sql: str) -> str:
        return sql.replace("?", self.ph) if self.ph != "?" else sql

    def _put(self, table: str, obj: Dict[str, Any], columns: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Upsert a document. Key columns come from `columns` when given there, else from the document."""
        columns = columns or {}
        cols = ["id", "created_at", "data"] + TABLES[table]
        vals = [obj["id"], obj["created_at"], self._json(obj)] + [columns[c] if c in columns else obj.get(c)
                                                                    for c in TABLES[table]]
        updates = ", ".join("%s = excluded.%s" % (c, c) for c in cols[1:])
        self._exec(self._q("INSERT INTO %s (%s) VALUES (%s) ON CONFLICT (id) DO UPDATE SET %s"
                           % (table, ", ".join(cols), ", ".join("?" * len(cols)), updates)), vals)
        self._after_put(table, obj)
        return obj

    def _get(self, table: str, id_: str) -> Optional[Dict[str, Any]]:
        rows = self._rows(self._q("SELECT data FROM %s WHERE id = ?" % table), (id_,))
        return self._load(rows[0]["data"]) if rows else None

    def _list(self, table: str, where: str = "", args: Sequence[Any] = (), order: str = "seq") -> List[Dict[str, Any]]:
        sql = "SELECT data FROM %s %s ORDER BY %s" % (table, ("WHERE " + where) if where else "", order)
        return [self._load(r["data"]) for r in self._rows(self._q(sql), args)]

    def _column(self, table: str, column: str, id_: Optional[str]) -> Optional[str]:
        if not id_:
            return None
        rows = self._rows(self._q("SELECT %s AS v FROM %s WHERE id = ?" % (column, table)), (id_,))
        return rows[0]["v"] if rows else None

    # ------------------------------------------------------------ generic documents (accounts, spec 011)
    @staticmethod
    def _where(table: str, eq: Dict[str, Any]):
        allowed = set(TABLES[table]) | {"id"}
        bad = sorted(set(eq) - allowed)
        if bad:
            raise ValueError("unknown column(s) %s for %s" % (bad, table))
        keys = sorted(eq)
        return " AND ".join("%s = ?" % k for k in keys), [eq[k] for k in keys]

    def put(self, table: str, obj: Dict[str, Any]) -> Dict[str, Any]:
        return self._put(table, obj)

    def get(self, table: str, id_: str) -> Optional[Dict[str, Any]]:
        return self._get(table, id_)

    def find(self, table: str, order: str = "seq", **eq: Any) -> List[Dict[str, Any]]:
        cache = self._prefetched()
        if (cache is not None and order == "seq" and list(eq) == ["parcel_id"] and table in cache["find"]
                and eq["parcel_id"] in cache["ids"]):
            import copy
            return copy.deepcopy(cache["find"][table].get(eq["parcel_id"], []))
        where, args = self._where(table, eq)
        return self._list(table, where, args, order)

    def delete(self, table: str, **eq: Any) -> None:
        if not eq:
            raise ValueError("delete without a condition")
        where, args = self._where(table, eq)
        self._exec(self._q("DELETE FROM %s WHERE %s" % (table, where)), args)

    def insert_new(self, table: str, obj: Dict[str, Any]) -> bool:
        """Insert a document only when no row with the same id or unique key exists (spec 025: claims of
        idempotency keys). True when this call inserted it; a concurrent insert of the same key returns False."""
        cols = ["id", "created_at", "data"] + TABLES[table]
        vals = [obj["id"], obj["created_at"], self._json(obj)] + [obj.get(c) for c in TABLES[table]]
        self._exec(self._q("INSERT INTO %s (%s) VALUES (%s) ON CONFLICT DO NOTHING"
                           % (table, ", ".join(cols), ", ".join("?" * len(cols)))), vals)
        stored = self._get(table, obj["id"])
        return bool(stored) and stored.get("nonce") == obj.get("nonce")

    def delete_before(self, table: str, column: str, value: str) -> None:
        """Delete rows whose key column `column` sorts before `value` (spec 025: expired idempotency keys)."""
        if column not in TABLES[table]:
            raise ValueError("unknown column %s for %s" % (column, table))
        self._exec(self._q("DELETE FROM %s WHERE %s < ?" % (table, column)), (value,))

    def orphan_parcel_count(self) -> int:
        rows = self._rows("SELECT count(*) AS n FROM parcels WHERE org_id IS NULL")
        return int(rows[0]["n"]) if rows else 0

    def assign_orphans(self, org_id: str) -> int:
        """Migration (spec 011): parcels stored before accounts existed get `org_id`; their profiles,
        conversations and runs inherit it. Returns the number of parcels assigned."""
        with self.transaction():                     # spec 052: all or nothing
            orphans = self._list("parcels", "org_id IS NULL")
            for parcel in orphans:
                parcel["org_id"] = org_id
                self._put("parcels", parcel)
            self.backfill_org_columns()
        return len(orphans)

    def backfill_org_columns(self) -> None:
        for table in ("profiles", "conversations"):
            self._exec("UPDATE %s SET org_id = (SELECT parcels.org_id FROM parcels WHERE parcels.id = %s.parcel_id) "
                       "WHERE org_id IS NULL" % (table, table))
        self._exec("UPDATE runs SET org_id = (SELECT conversations.org_id FROM conversations "
                   "WHERE conversations.id = runs.conversation_id) WHERE org_id IS NULL")

    # ------------------------------------------------------------ parcels
    def save_parcel(self, parcel: Dict[str, Any]) -> Dict[str, Any]:
        return self._put("parcels", parcel)

    def get_parcel(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("parcels", id_)

    def list_parcels(self, org_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every parcel (internal and research use) or, with org_id, the organisation's parcels."""
        if org_id is not None:
            return self._list("parcels", "org_id = ?", (org_id,), "seq DESC")
        return self._list("parcels", order="seq DESC")

    def delete_parcel(self, id_: str) -> None:
        """Every statement in one transaction (spec 052, DATA-3): a failure leaves no orphans."""
        with self.transaction():
            self._exec(self._q("DELETE FROM runs WHERE conversation_id IN (SELECT id FROM conversations "
                               "WHERE parcel_id = ?)"), (id_,))
            self._exec(self._q("DELETE FROM conversations WHERE parcel_id = ?"), (id_,))
            self._exec(self._q("DELETE FROM profiles WHERE parcel_id = ?"), (id_,))
            self._exec(self._q("DELETE FROM media WHERE parcel_id = ?"), (id_,))           # spec 023 (files: Media)
            self._exec(self._q("DELETE FROM field_crops WHERE parcel_id = ?"), (id_,))     # spec 027 (events stay: audit)
            self._exec(self._q("DELETE FROM field_access WHERE parcel_id = ?"), (id_,))    # spec 027 grants
            self._exec(self._q("DELETE FROM parcels WHERE id = ?"), (id_,))

    # ------------------------------------------------------------ activity log (spec 013)
    def save_activity(self, activity: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert an activity; the lot id of a harvest is a key column for lot lookups."""
        lot = (activity.get("details") or {}).get("lot_id") if activity.get("kind") == "harvest" else None
        return self._put("activities", activity, {"lot_id": lot or None})

    def add_activity_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Append-only: a new id every time, never updated."""
        if self._get("activity_events", event["id"]):
            raise ValueError("activity events are append-only")
        return self._put("activity_events", event)


    # ------------------------------------------------------------ field crops (spec 027)
    def save_field_crop(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a field crop; the season key column is text on both backends (the document keeps the integer)."""
        return self._put("field_crops", row, {"season": str(row["season"]) if row.get("season") is not None else None})

    # ------------------------------------------------------------ profiles
    def save_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        # The org_id column follows the parcel; the document itself is unchanged.
        return self._put("profiles", profile, {"org_id": self._column("parcels", "org_id", profile.get("parcel_id"))})

    def get_profile(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("profiles", id_)

    def latest_profile(self, parcel_id: str) -> Optional[Dict[str, Any]]:
        cache = self._prefetched()
        if cache is not None and parcel_id in cache["ids"]:
            import copy
            return copy.deepcopy(cache["profiles"].get(parcel_id))
        rows = self._list("profiles", "parcel_id = ?", (parcel_id,), "seq DESC LIMIT 1")
        return rows[0] if rows else None

    # ------------------------------------------------------------ external cache
    def cache_get(self, request_hash: str) -> Optional[Dict[str, Any]]:
        rows = self._rows(self._q("SELECT response, fetched_at FROM external_cache WHERE request_hash = ?"), (request_hash,))
        if not rows:
            return None
        return {"response": self._load(rows[0]["response"]), "fetched_at": self._iso(rows[0]["fetched_at"])}

    def cache_put(self, request_hash: str, provider: str, request: Dict[str, Any], response: Any,
                  fetched_at: Optional[str] = None) -> str:
        """Store a provider response. fetched_at is given only when importing a cache snapshot."""
        fetched = fetched_at or now_iso()
        self._exec(self._q("INSERT INTO external_cache (request_hash, provider, fetched_at, request, response) "
                           "VALUES (?, ?, ?, ?, ?) ON CONFLICT (request_hash) DO UPDATE SET "
                           "fetched_at = excluded.fetched_at, response = excluded.response"),
                   (request_hash, provider, fetched, self._json(request), self._json(response)))
        return fetched

    def cache_entries(self) -> List[Dict[str, Any]]:
        """Every cache entry ordered by request_hash (for snapshot export)."""
        rows = self._rows("SELECT request_hash, provider, fetched_at, request, response FROM external_cache "
                          "ORDER BY request_hash")
        return [{"request_hash": r["request_hash"], "provider": r["provider"], "fetched_at": self._iso(r["fetched_at"]),
                 "request": self._load(r["request"]), "response": self._load(r["response"])} for r in rows]

    @staticmethod
    def _iso(value: Any) -> str:
        return value.astimezone().isoformat(timespec="seconds") if isinstance(value, datetime) else str(value)

    # ------------------------------------------------------------ conversations and runs
    def save_conversation(self, conv: Dict[str, Any]) -> Dict[str, Any]:
        return self._put("conversations", conv, {"org_id": self._column("parcels", "org_id", conv.get("parcel_id"))})

    def get_conversation(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("conversations", id_)

    def list_conversations(self, parcel_id: str) -> List[Dict[str, Any]]:
        return self._list("conversations", "parcel_id = ?", (parcel_id,), "seq DESC")

    def save_run(self, run: Dict[str, Any]) -> Dict[str, Any]:
        return self._put("runs", run, {"org_id": self._column("conversations", "org_id", run.get("conversation_id"))})

    def get_run(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("runs", id_)

    def list_runs(self, conversation_id: str) -> List[Dict[str, Any]]:
        return self._list("runs", "conversation_id = ?", (conversation_id,), "turn")

    # ------------------------------------------------------------ evaluation
    def save_eval_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return self._put("eval_items", item)

    def get_eval_item(self, id_: str) -> Optional[Dict[str, Any]]:
        return self._get("eval_items", id_)

    def list_eval_items(self, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if batch_id:
            return self._list("eval_items", "batch_id = ?", (batch_id,))
        return self._list("eval_items")

    def save_rating(self, rating: Dict[str, Any]) -> Dict[str, Any]:
        with self.transaction():                     # spec 052: replace = delete + insert, atomically
            self._exec(self._q("DELETE FROM ratings WHERE item_id = ? AND rater = ?"), (rating["item_id"], rating["rater"]))
            return self._put("ratings", rating)

    def list_ratings(self, rater: Optional[str] = None) -> List[Dict[str, Any]]:
        if rater:
            return self._list("ratings", "rater = ?", (rater,))
        return self._list("ratings")


# ---------------------------------------------------------------------------------------- SQLite

def _sqlite_schema() -> str:
    parts = []
    for table, extra in TABLES.items():
        cols = "".join(", %s %s" % (c, "INTEGER" if c in ("turn", "repeat") else "TEXT") for c in extra)
        parts.append("CREATE TABLE IF NOT EXISTS %s (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, "
                     "created_at TEXT, data TEXT%s);" % (table, cols))
    parts.append("CREATE TABLE IF NOT EXISTS external_cache (request_hash TEXT PRIMARY KEY, provider TEXT, "
                 "fetched_at TEXT, request TEXT, response TEXT);")
    parts += [stmt + ";" for stmt in _typed_schema("sqlite")]          # spec 035 time series (additive)
    return "\n".join(parts)


class SqliteStore(Store):
    backend = "sqlite"

    def __init__(self, path: Optional[str] = None, migrate: bool = True):
        path = path or os.environ.get("SMARTAGRI_DB", str(Path.cwd() / "smartagri.sqlite"))
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Spec 052: re-entrant, so a transaction() block can hold it while its statements run.
        self._lock = threading.RLock()
        self._local = threading.local()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if migrate:
            from .migrate import schema_up
            schema_up(self)

    def sync_schema(self) -> None:
        """Idempotent DDL for every table, key column and index (migration 0001 and the schema sync, spec 052)."""
        with self._lock:
            self._db.executescript(_sqlite_schema())
            self._migrate()

    def _migrate(self) -> None:
        """Add key columns introduced after a database was created (e.g. org_id, spec 011), then indexes."""
        for table, extra in TABLES.items():
            have = {r["name"] for r in self._db.execute("PRAGMA table_info(%s)" % table).fetchall()}
            for c in extra:
                if c not in have:
                    self._db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, c, "INTEGER" if c in ("turn", "repeat") else "TEXT"))
        for stmt in INDEXES:
            self._db.execute(stmt)
        self._db.commit()

    def _in_tx(self) -> bool:
        return getattr(self._local, "depth", 0) > 0

    def _exec(self, sql, args=()):
        with self._lock:
            self._db.execute(sql, args)
            if not self._in_tx():
                self._db.commit()

    def _rows(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    @contextlib.contextmanager
    def transaction(self):
        with self._lock:
            depth = getattr(self._local, "depth", 0)
            self._local.depth = depth + 1
            try:
                yield self
            except BaseException:
                self._local.depth = depth
                if depth == 0:
                    self._db.rollback()
                raise
            self._local.depth = depth
            if depth == 0:
                self._db.commit()

    @contextlib.contextmanager
    def migration_lock(self):
        with self._lock:
            yield

    def close(self) -> None:
        self._db.close()


# ------------------------------------------------------------------------------------ PostgreSQL

EMBEDDING_DIM = 384


def _pg_schema() -> List[str]:
    stmts = ["CREATE EXTENSION IF NOT EXISTS postgis", "CREATE EXTENSION IF NOT EXISTS vector"]
    for table, extra in TABLES.items():
        cols = "".join(", %s %s" % (c, "INTEGER" if c in ("turn", "repeat") else "TEXT") for c in extra)
        stmts.append("CREATE TABLE IF NOT EXISTS %s (seq BIGSERIAL PRIMARY KEY, id TEXT UNIQUE NOT NULL, "
                     "created_at TIMESTAMPTZ NOT NULL, data JSONB NOT NULL%s)" % (table, cols))
    for table, extra in TABLES.items():          # columns added after a database was created (spec 011: org_id)
        stmts += ["ALTER TABLE %s ADD COLUMN IF NOT EXISTS %s %s" % (table, c, "INTEGER" if c in ("turn", "repeat") else "TEXT")
                  for c in extra]
    stmts += INDEXES
    stmts += [
        "ALTER TABLE parcels ADD COLUMN IF NOT EXISTS geom geometry(Polygon, 4326)",
        "CREATE INDEX IF NOT EXISTS parcels_geom_idx ON parcels USING gist (geom)",
        "CREATE INDEX IF NOT EXISTS profiles_parcel_idx ON profiles (parcel_id, seq)",
        "CREATE INDEX IF NOT EXISTS runs_conversation_idx ON runs (conversation_id, turn)",
        "CREATE TABLE IF NOT EXISTS external_cache (request_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, "
        "fetched_at TIMESTAMPTZ NOT NULL, request JSONB NOT NULL, response JSONB NOT NULL)",
        "CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL, text TEXT NOT NULL, "
        "meta JSONB NOT NULL, corpus_hash TEXT NOT NULL, model TEXT NOT NULL, embedding vector(%d) NOT NULL)" % EMBEDDING_DIM,
    ]
    stmts += _typed_schema("postgresql")                              # spec 035 time series (additive)
    return stmts


class _SingleConnection:
    """Fallback when psycopg_pool is not installed: one connection, re-opened when it is closed or broken."""

    def __init__(self, connect):
        self._connect = connect
        self._conn = None
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def connection(self, timeout: Optional[float] = None):
        with self._lock:
            if self._conn is None or self._conn.closed or self._conn.broken:
                self._conn = self._connect()
            yield self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()


# Advisory lock key of the migration runner (spec 052): "AGROVID" in ASCII, fits a bigint.
MIGRATION_LOCK_KEY = 0x4147524F564944


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


class PostgresStore(Store):
    """PostgreSQL 16 with PostGIS (parcel geometry) and pgvector (passage embeddings).

    Spec 052 (audit REL-1, PERF-2): a connection pool (psycopg_pool) instead of one connection behind a global lock.
    Connections idle for more than IDLE_CHECK_S are checked before use, broken ones are discarded, so the store
    recovers by itself after a database restart; a failed call raises DatabaseUnavailable (HTTP 503). Pool size:
    AGROVID_DB_POOL_MIN (1) / AGROVID_DB_POOL_MAX (10), wait for a free connection AGROVID_DB_POOL_TIMEOUT s (10)."""
    backend = "postgresql"
    ph = "%s"
    IDLE_CHECK_S = 2.0

    def __init__(self, url: str, migrate: bool = True):
        import psycopg                                  # imported lazily: SQLite users do not need it
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
        self._psycopg = psycopg
        self._Jsonb = Jsonb
        self._lock = threading.Lock()                   # deprecated (spec 052): statements no longer take it
        self._local = threading.local()
        self._last_used: Dict[int, float] = {}
        kwargs = {"autocommit": True, "row_factory": dict_row, "connect_timeout": 5}
        timeout = float(_env_int("AGROVID_DB_POOL_TIMEOUT", 10))
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:                             # pragma: no cover - the pg extra installs it
            log.warning("psycopg_pool is not installed; using one reconnecting connection")
            self._pool = _SingleConnection(lambda: psycopg.connect(url, **kwargs))
        else:
            self._pool = ConnectionPool(url, min_size=_env_int("AGROVID_DB_POOL_MIN", 1),
                                        max_size=max(1, _env_int("AGROVID_DB_POOL_MAX", 10)), kwargs=kwargs,
                                        timeout=timeout, check=self._check, open=False, name="agrovid")
            self._pool.open(wait=True, timeout=timeout)
        if migrate:
            from .migrate import schema_up
            schema_up(self)

    # ------------------------------------------------------------ connections
    def _check(self, conn) -> None:
        last = self._last_used.get(id(conn))
        if last is None or time.monotonic() - last > self.IDLE_CHECK_S:
            conn.execute("SELECT 1")                    # raises on a dead connection: the pool takes another one

    def _check_idle(self) -> None:
        check = getattr(self._pool, "check", None)
        if check is not None:
            try:
                check()                             # psycopg_pool: test idle connections, replace broken ones
            except Exception:
                log.warning("pool check failed", exc_info=True)

    @contextlib.contextmanager
    def _connection(self):
        bound = getattr(self._local, "conn", None)
        if bound is not None:
            yield bound
            return
        with self._pool.connection() as conn:
            try:
                yield conn
            finally:
                self._last_used[id(conn)] = time.monotonic()

    def _run(self, sql, args, fetch: bool):
        retry = fetch and getattr(self._local, "conn", None) is None and sql.lstrip()[:6].upper() == "SELECT"
        for attempt in (0, 1):
            try:
                with self._connection() as conn:
                    cur = conn.execute(sql, args)
                    return cur.fetchall() if fetch else None
            except self._psycopg.OperationalError as exc:
                # A read outside a transaction is retried once (a connection that died since its last check).
                if retry and attempt == 0 and type(exc).__name__ != "PoolTimeout":
                    self._check_idle()              # the other idle connections died with it (database restart)
                    continue
                raise DatabaseUnavailable("%s: %s" % (type(exc).__name__, str(exc)[:200])) from exc

    def _exec(self, sql, args=()):
        self._run(sql, args, False)

    def _rows(self, sql, args=()):
        return self._run(sql, args, True)

    @contextlib.contextmanager
    def transaction(self):
        bound = getattr(self._local, "conn", None)
        if bound is not None:                           # nested: a savepoint inside the outer transaction
            with bound.transaction():
                yield self
            return
        with self._pool.connection() as conn:
            self._local.conn = conn
            try:
                with conn.transaction():
                    yield self
            finally:
                self._local.conn = None
                self._last_used[id(conn)] = time.monotonic()

    @contextlib.contextmanager
    def migration_lock(self):
        """Session advisory lock on one pooled connection; every statement of the block runs on it (spec 052)."""
        with self._pool.connection() as conn:
            prev = getattr(self._local, "conn", None)
            self._local.conn = conn
            try:
                conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
                try:
                    yield
                finally:
                    if not conn.closed and not conn.broken:
                        conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
            finally:
                self._local.conn = prev

    def sync_schema(self) -> None:
        """Idempotent DDL for every table, key column, index and extension (migration 0001, schema sync)."""
        for stmt in _pg_schema():
            self._exec(stmt)

    def close(self) -> None:
        self._pool.close()

    def _json(self, obj):
        return self._Jsonb(obj)

    def _after_put(self, table, obj):
        if table == "parcels":
            self._exec("UPDATE parcels SET geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) WHERE id = %s",
                       (json.dumps(obj["geometry"]), obj["id"]))

    # ------------------------------------------------------------ PostGIS
    def parcel_area_ha(self, parcel_id: str) -> Optional[float]:
        """Area on the WGS84 spheroid as computed by PostGIS; used to cross-check geo.area_ha."""
        rows = self._rows("SELECT ST_Area(geom::geography) / 10000.0 AS ha, ST_IsValid(geom) AS valid "
                          "FROM parcels WHERE id = %s", (parcel_id,))
        return float(rows[0]["ha"]) if rows and rows[0]["ha"] is not None else None

    # ------------------------------------------------------------ pgvector
    @staticmethod
    def _vec(vector: Sequence[float]) -> str:
        return "[" + ",".join("%.7f" % x for x in vector) + "]"

    def indexed_corpus(self) -> Optional[Dict[str, Any]]:
        rows = self._rows("SELECT corpus_hash, model, count(*) AS n FROM chunks GROUP BY corpus_hash, model")
        return dict(rows[0]) if len(rows) == 1 else None

    def replace_chunks(self, corpus_hash: str, model: str, chunks: List[Dict[str, Any]]) -> None:
        with self.transaction():
            self._exec("DELETE FROM chunks")
            for c in chunks:
                self._exec(
                    "INSERT INTO chunks (id, document_id, text, meta, corpus_hash, model, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s::vector)",
                    (c["id"], c["document_id"], c["text"], self._Jsonb(c["meta"]), corpus_hash, model, self._vec(c["embedding"])))

    def nearest_chunks(self, vector: Sequence[float], k: int = 50) -> List[str]:
        rows = self._rows("SELECT id FROM chunks ORDER BY embedding <=> %s::vector, id LIMIT %s", (self._vec(vector), k))
        return [r["id"] for r in rows]


def make_store(url: Optional[str] = None, migrate: bool = True) -> Store:
    """PostgreSQL when DATABASE_URL is set, otherwise SQLite. `migrate=False` (spec 052, migration CLI): no schema
    migrations at construction."""
    url = url if url is not None else os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres"):
        return PostgresStore(url.replace("postgresql+psycopg://", "postgresql://"), migrate=migrate)
    return SqliteStore(migrate=migrate)
