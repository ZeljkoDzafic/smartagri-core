"""Hourly weather series of the product: derived variables, precedence/merge and storage.

Separate from the daily weather profile of the core decision model (`providers/weather.py`, unchanged): nothing in
this package feeds context C, q, sigma, alpha or delta; evalkit never imports it.
"""
