from night_shift.adapters.sources.ats import ATS_SOURCES
from night_shift.adapters.sources.gupy import GupySource
from night_shift.adapters.sources.http import PoliteClient
from night_shift.config import CompanyConfig, Preferences
from night_shift.ports import JobSource


def build_sources(
    http: PoliteClient, companies: list[CompanyConfig], prefs: Preferences
) -> list[JobSource]:
    sources: list[JobSource] = [
        ATS_SOURCES[c.ats](http, c) for c in companies if c.ats in ATS_SOURCES and c.slug
    ]
    if prefs.gupy_search_terms:
        sources.append(GupySource(http, prefs.gupy_search_terms))
    return sources
