Carousel Pipeline — Read This In Order

Big task: post 3-4 motivational carousels a day to IG + FB, unattended.

Five small tasks make up the big one. Read the files in this order —
each chapter finishes one small task before the next begins.

carousel-pipeline/
├── README.md                  ← you are here
├── queue_manager.py            [Ch 1: Remember what's done today]
├── generate_thought.py         [Ch 2: Write today's quotes]
├── generate_background.py      [Ch 3: Paint today's backgrounds]
├── compose_carousel.py         [Ch 4: Stamp text onto the paint]
├── run_pipeline.py             [Ch 5: The story that calls chapters 1-4, then posts]
├── post_carousel.py            [Ch 6: Hand the finished images to Instagram/Facebook]
├── carousel-pipeline.yml       [The narrator: fires Ch 5 four times a day]
├── state/queue.json            [Ch 1's notebook — auto-created, don't edit by hand]
└── output/                     [scratch folder for rendered images, safe to delete anytime]


Chapter 1 — queue_manager.py — "Remember what's done today"

One line: Did we already post today's 4 carousels, or not?
Reads/writes state/queue.json. If the date changed, forgets yesterday and starts fresh.
Finished when: you can answer "what's left to post today" without re-checking IG yourself.

Chapter 2 — generate_thought.py — "Write today's quotes"

One line: Ask Groq for 4 quotes, in one of your 3 approved styles (tricolon / contrarian-hook / listicle).
Finished when: you have 4 quotes, each already split into slide 1/2/3 text.
External dependency: Groq API (GROQ_API_KEY) — free tier, already in use in your other pipelines.

Chapter 3 — generate_background.py — "Paint today's backgrounds"

One line: Ask Ideogram for a flat mustard/cream/mint background with a small doodle — no text baked in.
Finished when: you have a blank styled canvas, per slide, ready for text.
External dependency: Ideogram API (IDEOGRAM_API_KEY) — paid, ~$0.03–0.08/image.

Chapter 4 — compose_carousel.py — "Stamp text onto the paint"

One line: Take Chapter 3's canvas + Chapter 2's text, overlay text with Pillow (exact, no AI-text risk).
Finished when: 3 slide PNGs exist on disk, 1080×1080, brand-consistent every day.
External dependency: none — pure local render, already self-tested.

Chapter 5 — run_pipeline.py — "The story that ties it together"

One line: Check Chapter 1 → if needed, run Ch 2+3 → run Ch 4 → push images to GitHub → call Chapter 6 → tell Chapter 1 it's done.
Finished when: one command does the whole day's work, idempotently.
External dependency: none directly — orchestrates the others.

Chapter 6 — post_carousel.py — "Hand it to Instagram/Facebook"

One line: 3-step Graph API dance: create child containers → wrap in a carousel container → publish.
Finished when: the carousel is live on both platforms, and you have back an IG media ID + FB post ID.
External dependency: Meta Graph API (IG_USER_ID, FB_PAGE_ID, META_SYSTEM_USER_TOKEN).

The Narrator — carousel-pipeline.yml

One line: Wakes Chapter 5 up 4 times a day, on schedule, inside GitHub Actions.
Reads all 4 external-dependency secrets from GitHub repo settings, hands them to Chapter 5 as environment variables.


External dependencies — all 4, at a glance

SecretWho issues itCostBlocks which chapterGROQ_API_KEYconsole.groq.comFreeCh 2IDEOGRAM_API_KEYideogram.ai/apiPay-per-image, no subscription — ~$0.025-0.03/image (Turbo tier). ~$8-10/mo at 4 carousels/day. Official pricingCh 3IG_USER_IDDerived, not issued directly — see chain belowFreeCh 6FB_PAGE_IDDerived, not issued directly — see chain belowFreeCh 6META_SYSTEM_USER_TOKENMeta Business ManagerFreeCh 6

⚠️ Correction from earlier in this build: Ideogram API is pay-per-image via the official page, not a locked monthly subscription as one third-party source claimed. If you want $0 instead, swap to Pollinations.ai in generate_background.py — lower aesthetic control, zero cost.

IG_USER_ID + FB_PAGE_ID — one setup chain, new accounts

Both of you are creating new IG + FB accounts for this. Order matters — IG_USER_ID cannot exist before steps 1-4 are done.

1. Create a new Facebook Page (not a personal profile)
   facebook.com → Create → Page → choose a Business/Brand category
   → this Page's numeric ID = FB_PAGE_ID (found under Page → About → Page transparency)

2. Create a new Instagram account (or use existing)
   → Settings → Account type → switch to Professional → choose Creator or Business

3. Link the IG account to the Page from step 1
   → IG app → Settings → Business tools and controls → Connect Facebook Page
   → select the Page created in step 1

4. Both must land in the SAME Meta Business Manager
   business.facebook.com → Business Settings → Accounts
   → add the Page (step 1) and the IG account (step 2) if not already there

5. Create a Meta App (developer surface, separate from the Business Manager)
   developers.facebook.com → My Apps → Create App → type "Business"
   → Add products: "Instagram Graph API" + "Facebook Login for Business"

6. Fetch the IDs via Graph API Explorer
   Tools → Graph API Explorer → select your app → Generate User Token
   → scopes: instagram_basic, instagram_content_publish, pages_show_list,
     pages_manage_posts, pages_read_engagement
   → GET /me/accounts  → returns Page id  = FB_PAGE_ID (confirm matches step 1)
   → GET /{FB_PAGE_ID}?fields=instagram_business_account
     → returns IG_USER_ID (only resolves if steps 1-4 are done correctly)

7. Generate the PERMANENT token (do NOT use the Explorer token from step 6 above —
   that one expires in ~1-2 hours, debug-only)
   business.facebook.com → Business Settings → Users → System Users → Add
   → assign the Page + IG asset from step 4 to this System User
   → Generate New Token → same scopes as step 6 → this is META_SYSTEM_USER_TOKEN

Open blocker, still unresolved: none — this chain now fully specifies new-account creation. Confirm once all 7 steps are done before wiring secrets into GitHub.
