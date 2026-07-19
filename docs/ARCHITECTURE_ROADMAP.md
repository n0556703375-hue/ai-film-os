# AI Film OS — Architecture Roadmap

## Product goal
A production operating system that turns a complete screenplay into approved, continuity-safe image, video and audio assets, organized by project, scene and shot.

## Delivery order

### 1. Production foundation
- Full screenplay import
- Scene breakdown
- Automatic shot maps
- Prompt and media versioning
- Project-wide progress totals

### 2. Character Lock
- One approved master identity per character
- Approved reference gallery by view and expression
- Draft / review / locked status
- Only locked references flow into shot generation
- Identity drift checks

### 3. Location and wardrobe lock
- Master location and wardrobe references
- Scene-level state variants
- Automatic reference propagation

### 4. Shot approval pipeline
- Planned → prompt ready → image draft → image approved → video draft → video approved → final
- Batch actions and filters
- Explicit approval history

### 5. Video production
- Image-to-video generation
- Model selection by shot requirements
- Duration, camera motion and audio controls
- Generation polling and media version storage

### 6. Continuity Director
- Compare each shot with previous and next shots
- Character, wardrobe, prop, lighting, geography and eyeline checks
- Block final approval for critical unresolved issues

### 7. Scene assembly
- Timeline ordered by shot number
- Duration totals
- Preview export manifest
- Audio and dialogue tracking

### 8. Production reliability
- Background job queue
- Retry and idempotency
- Cost and credit tracking
- Automated tests and deployment checks

## Engineering rules
- Never develop directly on `main`.
- One focused branch and pull request per capability.
- Preserve existing project data through additive migrations.
- Require explicit confirmation before destructive replacement.
- Keep provider credentials in environment variables only.
- Merge only after tests and review checks pass.
