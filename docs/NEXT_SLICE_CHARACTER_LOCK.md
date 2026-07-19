# Next Vertical Slice: Character Lock

## User outcome
The producer can choose one approved character identity, lock it, and guarantee that every new shot uses only that identity reference.

## Acceptance criteria
- Character assets have `lock_status`: draft, review, locked.
- A character can have one master reference and multiple approved secondary references.
- Locking requires a master reference.
- Shot generation receives only approved references from the locked character.
- Replacing a locked master requires explicit confirmation and records the change.
- Story Bible clearly displays locked state and master image.
- Tests cover locking, replacement protection and shot-reference propagation.

## Implementation plan
1. Add additive database migration for lock state and master reference.
2. Extend asset schemas and repository methods.
3. Add lock/unlock API endpoints.
4. Update Story Bible UI.
5. Enforce lock selection in generation services.
6. Add automated tests.
