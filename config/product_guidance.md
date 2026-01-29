# Product Direction

The product displays PI Vision display information. Feature-wise, core needs are met.
Auto-feature creation should remain **off** unless new requirements are added below.

## High-level requirements (auto-feature runs while any are unchecked)
- [x] Display PI Vision metadata (name, owner, folder, timestamps, etc.)
- [x] Provide search/filter/sort experience for displays
- [x] Provide clear empty-state + error handling for search

## Target users / use cases
- Ops/engineering users who need a quick inventory of PI Vision displays
- Troubleshooting owners/locations without opening PI Vision

## Success criteria
- Search returns accurate results (including exact numeric owner IDs)
- Errors are clear and actionable

## Constraints / non-goals
- No new major features unless explicitly requested
- Focus on bug fixes and stability

## Potential future (do not auto-create issues)
- Authentication/authorization (only if requested explicitly)
