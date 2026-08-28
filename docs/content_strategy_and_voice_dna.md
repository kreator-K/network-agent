# Content strategy and voice DNA

Content-package generation remains coordinated by `ContentInspirationAgent`
through four incorporated specialists: `ContentResearchAgent`,
`HookWriterAgent`, `CarouselMakerAgent`, and `CaptionWriterAgent`. Their
responsibilities follow the reference packages' research → hook → carousel →
caption handoff, but their artifacts are frozen inside the existing SQLite
package JSON and all model calls use `ModelOrchestrationAgent`. This feature
does not add a scheduler, social-platform connector, or publishing path.

## Planning contract

Every newly generated source-traced package freezes:

- one editorial pillar from the weekday rotation;
- one topical pillar from the referenced personal-brand profile;
- a TOF, MOF, or BOF funnel position;
- three complete post variants with named hook archetypes;
- two alternate opening lines in a Hook A/B block; and
- one evidence-preserving adjustment to test if the post underperforms.

The weekday rotation is Education/TOF, Contrarian POV/TOF, Authority/MOF,
Story/MOF, and Offer-adjacent/BOF. Hook compatibility is deterministic in
`config/content_strategy.py`. The model receives the frozen plan and must return
the exact structured contract through `ModelOrchestrationAgent`. Invalid or
partial model fields fall back to the deterministic, source-grounded package.

## Voice DNA

The personal-brand profile includes sentence rhythm, preferred and prohibited
vocabulary, formatting rules, point-of-view rules, and reference notes. These
fields are human-controlled and versioned with the rest of the profile. They do
not grant permission to invent experiences or personal claims. The profile seed
also carries the `kreator_K` brand guide's audience, visual palette, typography,
imagery rules, raw build-log direction, content do/avoid rules, and direct CTA
style. These guide visual briefs and copy context; they do not authorize use of
unverified claims or third-party media.

The JSON profile remains an initialization seed. Existing installations continue
using their active SQLite profile until the operator explicitly creates and
activates a new version containing the voice-DNA fields.

## Review and selection

Web package review shows the frozen plan, the selected primary post,
previews of all variants, Hook A/B options, and the underperformance adjustment.
Selecting another variant:

1. copies that complete variant into the primary draft;
2. appends an immutable package version;
3. resets the package to `draft` and clears prior approval; and
4. performs no LinkedIn or other provider write.

Only the selected primary draft can later enter the existing frozen-preview and
explicit `/confirm_publish` lifecycle.
