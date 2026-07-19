# Asset, Revision, Media, and Storage Model

Stimma separates user-facing identity from immutable payloads and physical
storage.

- **Assets** are stable items shown by All Assets, saved views, projects,
  boards, and Trash. Assets are durable roots and are never garbage-collected.
- **Asset Revisions** are immutable saved states. An Asset points at one current
  revision, so editing updates one browser card instead of creating clutter.
- **Media** records identify immutable payloads and their provenance. A chat,
  flow, editor, or container may retain Media without making it an Asset.
- **Storage Objects** contain managed bytes or identify verified external source
  files. Multiple Media records may safely share one managed object.

## Results and contextual media

Direct tool and declared flow results become Assets. Agent results must be shown
as either `intermediate` or `final`: final results become Assets, while
intermediates remain retained by their chat and can be searched or explicitly
saved later. Merely viewing an intermediate does not promote it.

Deleting a context releases its Media ownership. Media and managed bytes are
collected only when no Asset revision, container revision, snapshot, or other
live root retains them. Deleting a context never deletes its result Assets.

## Containers

Sets and grids are Assets. Each committed container revision contains normalized
members of two kinds:

- A linked member references an independent Asset and follows its current
  revision. The container does not own or exclusively contain that Asset.
- An embedded member references exact Media retained by the container revision.
  Saving that member as an Asset is idempotent and does not change the container's
  frozen result.

Assets can belong to any number of containers, projects, and boards. Saving all
container members as Assets promotes only embedded members, reuses linked or
already-saved Assets, and moves the container to Trash.

## Managed and external storage

New generated payloads, including set/grid manifests and layout bundles, are
written to private per-profile staging and immediately ingested into
Stimma-managed content-addressed storage. Uploads use the same private staging
path. Structured directories are hashed, verified, retained, and deleted as one
payload. The staging location is server-owned and cannot be selected by clients.
Legacy structured outputs under historical writable roots are adopted
automatically and incrementally at startup.

Settings calls watched folders **Sources**. Sources are optional and external.
Stimma never writes new files into a Source and never uses one as a generation
or upload destination. Deletion is the one mutation: emptying the trash
permanently deletes a trashed source file from disk, the same as managed
content. New profiles have no Sources by default. Managed storage paths are implementation
details; user serviceability should come from source access for external files
and explicit export/backup for managed content.

## Historical migration

Startup automatically classifies historical Media using normalized structured
membership and independent-use evidence. Ambiguous records become Assets so an
upgrade cannot hide previously visible content. Proven container-only members
remain embedded Media. The migration is deterministic and idempotent, advances
the profile to `contracted`, and no longer relies on the removed
`superseded_by` or `is_hidden` columns.

The first canary upgrade of a large real profile should be preceded by a backup
and used to validate counts, missing payloads, structured adoption, and browser
behavior. That validation is a rollout check, not a human classification step.
