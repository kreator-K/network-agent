# Phase 8B: Public Signal Foundation

## Purpose

Phase 8B provides a deterministic, approval-first foundation for storing and manually ingesting public RSS and Atom feeds. It stops at normalized, deduplicated SQLite signals. It does not rank signals, call models, draft posts, generate images, discover prospects, schedule work, or publish anything.

## Responsibilities

`public_signal_gateway` owns HTTP requests, conditional headers, redirect handling, response limits, XML parsing, and SSRF protection. It never writes SQLite or calls models.

`SignalIntelligenceAgent` owns normalization, canonical URLs, content hashes, deduplication, signal persistence, and scan summaries. It never performs HTTP, model, image, Telegram, or LinkedIn work.

`NetworkOrchestrator` coordinates source management and manual scans. Telegram handlers only parse commands and format responses.

## Supported Sources And Approval

Only RSS and Atom feeds are supported. New sources start as `pending`; they must be explicitly approved and enabled before `/scan_signal_source` can fetch them. Rejected or disabled sources cannot be scanned.

## Normalization And Deduplication

Titles, summaries, authors, and dates are whitespace-normalized. Canonical URLs drop fragments and common tracking parameters. A stable source GUID is preferred for same-source deduplication, then canonical URL, then a deterministic normalized-content hash. Cross-source matches retain a `duplicate` signal row with `duplicate_of_id` for source provenance.

## Safety

The gateway allows HTTPS by default, rejects embedded credentials, local/private/link-local/multicast/reserved network targets, validates DNS resolution, revalidates every redirect, limits redirects and response bytes, and blocks LinkedIn domains. It does not log feed bodies.

## SQLite

`signal_sources` stores user-approved source configuration and conditional-fetch metadata. `signals` stores raw attributed feed payload, normalized fields, hashes, dedupe data, and Phase 8B ingestion status. `config/signal_sources.json` intentionally contains an empty list and is not live source configuration.

## Telegram Commands

```text
/add_signal_source Example | https://example.org/feed.xml
/signal_sources
/approve_signal_source 3
/enable_signal_source 3
/scan_signal_source 3
/scan_signals
/signals
/signal 12
```

## Mock And Test Behavior

Gateway tests use mocked HTTP responses and DNS resolution. No real feed request is made by the test suite. Feed scanning is manual only.

## Known Limitations

There is no HTML scraping, JSON Feed support, source scoring, signal ranking, content opportunity, post generation, scheduler, or LinkedIn integration. Phase 8C will consume the stored normalized signals and active personal-brand profile for relevance scoring.
