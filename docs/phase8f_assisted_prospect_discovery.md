# Phase 8F: Assisted Prospect Discovery

Phase 8F extends `ProspectDiscoveryAgent` to create review-only candidates from already stored, approved public-signal author metadata. It does not crawl arbitrary pages, query LinkedIn, enrich from data brokers, infer sensitive attributes, or collect private contact details.

Candidates preserve signal IDs and source references, deterministic score metadata, and a recommended draft-only ask type. `/discover_candidates` creates cards, `/prospect_candidates` lists them, and `/approve_candidate <candidate_id>` is the sole path that converts an eligible candidate to a CRM prospect. Approval adds no outreach and no LinkedIn action.
