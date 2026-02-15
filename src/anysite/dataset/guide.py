"""Dataset configuration guide -- comprehensive reference for building pipeline configs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuideSection:
    """A section of the dataset configuration guide."""

    title: str
    description: str
    content: str
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "content": self.content,
            "examples": self.examples,
        }


# ---------------------------------------------------------------------------
# Section order — controls display order in `anysite dataset guide`
# ---------------------------------------------------------------------------

SECTION_ORDER: list[str] = [
    "workflow",
    "sources",
    "params",
    "dependencies",
    "chains",
    "fields_matrix",
    "llm",
    "transform",
    "export",
    "db_load",
    "storage",
    "schedule",
    "notifications",
    "incremental",
    "validation",
    "mistakes",
]


# ---------------------------------------------------------------------------
# Guide sections
# ---------------------------------------------------------------------------

GUIDE_SECTIONS: dict[str, GuideSection] = {
    # ------------------------------------------------------------------
    # workflow
    # ------------------------------------------------------------------
    "workflow": GuideSection(
        title="Agent Workflow",
        description="Step-by-step process for building dataset configs",
        content="""\
Follow these steps when building a new dataset pipeline:

STEP 1 — DISCOVER ENDPOINT FIELDS:
Run `anysite describe <endpoint>` to see input parameters (with examples,
defaults) and output fields (with nested structure). This tells you:
  - What parameters the endpoint expects (input_key, params)
  - What fields are in the output for dependency extraction (field)

    anysite describe /api/linkedin/user/posts
    anysite describe /api/linkedin/user/posts --json

STEP 2 — DRAFT YAML CONFIG:
Write the dataset YAML with sources, dependencies, and LLM steps.
Use the output fields from Step 1 to set correct `dependency.field` paths.

STEP 3 — VALIDATE:
Fast check (< 0.1s) catches structural errors, missing deps, bad filters:

    anysite dataset validate dataset.yaml --json

STEP 4 — DRY RUN:
Preview the collection plan with estimated request counts:

    anysite dataset collect dataset.yaml --dry-run

STEP 5 — COLLECT:
Run the actual collection:

    anysite dataset collect dataset.yaml
    anysite dataset collect dataset.yaml --load-db mydb

KEY RULE: ALWAYS run `anysite describe` before setting dependency.field.
The output fields show exactly which paths exist. For example,
`/api/linkedin/user/posts` output has `author` as
`object{@type,internal_id,urn,...}` — so the author's URN is
`author.urn.value`, NOT `urn.value` (which is the post's own URN).
""",
        examples=[
            """\
# Discover what an endpoint returns
anysite describe /api/linkedin/user --json""",
            """\
# Validate + dry-run before collecting
anysite dataset validate dataset.yaml --json
anysite dataset collect dataset.yaml --dry-run""",
        ],
    ),
    # ------------------------------------------------------------------
    # sources
    # ------------------------------------------------------------------
    "sources": GuideSection(
        title="Source Types",
        description="The five types of data sources you can define in a dataset pipeline",
        content="""\
Every dataset config has a top-level `sources:` list. Each source has a unique
`id` and an optional `type` field (default: "api"). The five source types are:

1. INDEPENDENT (type: api, no dependency, no from_file)
   Makes a single API call with static parameters.

     - id: search_results
       endpoint: /api/linkedin/search/users
       params:
         keywords: "software engineer"
         count: 50

2. FROM_FILE (type: api, with from_file)
   Iterates over values from a local file (.txt, .csv, .jsonl) and makes one
   API call per value.

     - id: profiles
       endpoint: /api/linkedin/user
       from_file: usernames.txt      # one value per line
       input_key: user               # API parameter name for each value
       parallel: 5                   # concurrent requests

   For CSV files, use `file_field` to specify which column to extract:

     - id: companies
       endpoint: /api/linkedin/company
       from_file: targets.csv
       file_field: company_name      # column name in CSV
       input_key: company
       parallel: 3

   For JSONL files, use `file_field` to specify the JSON key:

     - id: profiles
       endpoint: /api/linkedin/user
       from_file: users.jsonl
       file_field: username
       input_key: user

3. DEPENDENT (type: api, with dependency)
   Extracts values from a parent source's collected data and makes one API
   call per value.

     - id: profiles
       endpoint: /api/linkedin/user
       dependency:
         from_source: search_results   # parent source ID
         field: urn.value              # dot-notation path to extract
         dedupe: true                  # remove duplicate values
       input_key: user
       parallel: 5

4. UNION (type: union)
   Combines records from multiple parent sources into one virtual source.
   All parent sources must use the same endpoint. Useful for merging multiple
   search results before feeding into a dependent source.

     - id: all_candidates
       type: union
       sources: [search_sf, search_ny]   # parent source IDs
       dedupe_by: urn.value              # deduplicate on this field

5. LLM (type: llm)
   Processes records from a parent source through LLM steps without making any
   API calls. Requires a dependency and at least one LLM step.

     - id: enriched_profiles
       type: llm
       dependency:
         from_source: profiles
       llm:
         - type: classify
           categories: "active_seeker,passive,not_looking"
           fields: [headline, about]
           output_column: job_status

Sources are automatically topologically sorted by dependencies (Kahn's
algorithm), so you can list them in any order in the YAML file. Independent
and from_file sources run first, followed by dependent sources in order.

Common fields available on all API sources:
  parallel:    int    (default: 1)   concurrent requests
  rate_limit:  str    (e.g., "10/s") rate limiting
  on_error:    str    "stop" or "skip" (default: "skip")
  refresh:     str    "auto" or "always" (default: "auto")
""",
        examples=[
            """\
# Minimal independent source
- id: search
  endpoint: /api/linkedin/search/users
  params:
    keywords: "data scientist"
    count: 25""",
            """\
# From-file with CSV input
- id: profiles
  endpoint: /api/linkedin/user
  from_file: targets.csv
  file_field: linkedin_url
  input_key: user
  parallel: 5
  rate_limit: "10/s"
  on_error: skip""",
            """\
# Dependent source with input_template
- id: company_posts
  endpoint: /api/linkedin/company/posts
  dependency:
    from_source: companies
    field: universalName
    dedupe: true
  input_key: company
  input_template:
    company: "{value}"
    count: 20
  parallel: 3""",
        ],
    ),
    # ------------------------------------------------------------------
    # params
    # ------------------------------------------------------------------
    "params": GuideSection(
        title="Parameters",
        description="How to specify API parameters in source configs",
        content="""\
The `params` dict contains static API parameters sent with every request for a
source. All Anysite API endpoints use POST with a JSON body.

SIMPLE KEY-VALUE PAIRS:

    params:
      keywords: "software engineer"
      count: 50
      start: 0

INTEGER AND BOOLEAN VALUES:
Values are auto-typed. Integers and booleans work directly:

    params:
      count: 100
      includeHidden: true
      start: 0

STRING VALUES:
Use quotes for strings, especially those containing special characters:

    params:
      keywords: "CTO OR VP Engineering"
      location: "San Francisco Bay Area"

URN SYNTAX:
LinkedIn URNs are string identifiers used for profiles, companies, etc.:

    params:
      user: "urn:li:fsd_profile:ACoAABxxxxxxxxx"
      company: "urn:li:fsd_company:12345"

JSON ARRAY PARAMETERS:
Use YAML list syntax for array parameters:

    params:
      industries: [1, 2, 3]
      locations: ["us:84", "us:70"]

NESTED OBJECT PARAMETERS:
Use YAML dict syntax for nested objects:

    params:
      filters:
        currentCompany: ["Microsoft", "Google"]
        connectionOf: "ACoAABxxxxxxxxx"

Parameters from `params` are merged with the dynamic value from `input_key`
for dependent and from_file sources. The `input_key` value takes precedence
if there is a key conflict.
""",
        examples=[
            """\
# Search with multiple filters
params:
  keywords: "machine learning engineer"
  location: "San Francisco"
  count: 100
  industries: [1, 96]""",
            """\
# Company lookup by URN
params:
  company: "urn:li:fsd_company:1441"
  decorationId: "com.linkedin.voyager.deco.organization.web.WebFullCompany"
""",
        ],
    ),
    # ------------------------------------------------------------------
    # dependencies
    # ------------------------------------------------------------------
    "dependencies": GuideSection(
        title="Dependencies",
        description="How dependent sources extract values from parent source output",
        content="""\
Dependent sources use the `dependency` block to extract input values from a
parent source's collected Parquet data. This creates a pipeline where one
source feeds into another.

DEPENDENCY FIELDS:

  dependency:
    from_source: <parent_source_id>   # REQUIRED: parent source ID
    field: <dot.notation.path>        # field to extract (e.g., urn.value)
    match_by: <field_name>            # alternative: fuzzy match by name
    dedupe: true                      # remove duplicate extracted values

DOT-NOTATION FIELD EXTRACTION:
Use dot notation to reach into nested JSON objects stored in Parquet:

    field: urn.value                  # extracts "value" from {"urn": {"value": "..."}}
    field: company.universalName      # nested path
    field: experience[0].companyName  # first element of array

DEDUPLICATION:
When `dedupe: true`, duplicate extracted values are removed before making API
calls. This is important when the parent source contains many records that
reference the same entity (e.g., many profiles at the same company).

INPUT_KEY:
The `input_key` specifies which API parameter receives the extracted value:

    input_key: user         # extracted value goes to params.user
    input_key: company      # extracted value goes to params.company

INPUT_TEMPLATE:
Transform extracted values before passing to the API. Use `{value}` as a
placeholder for the extracted value:

    input_template:
      type: company
      value: "{value}"

    # If field extracts "microsoft", the API call becomes:
    # POST {"type": "company", "value": "microsoft"}

Another common pattern -- adding static params alongside the dynamic value:

    input_template:
      keywords: "CTO OR VP Engineering"
      company: "{value}"

REFRESH MODES:
Controls how dependent sources behave on incremental runs:

    refresh: auto      # (default) skip already-collected input values
    refresh: always    # re-collect every run regardless of cache

PROVENANCE TRACKING:
Dependent source records are automatically annotated with:
  _input_value:    the raw extracted value that produced the record
  _parent_source:  the parent source ID
These enable FK linking when loading into a relational database.
""",
        examples=[
            """\
# Simple dependency: profiles from search results
- id: profiles
  endpoint: /api/linkedin/user
  dependency:
    from_source: search_results
    field: urn.value
    dedupe: true
  input_key: user
  parallel: 5""",
            """\
# Dependency with input_template
- id: employee_search
  endpoint: /api/linkedin/search/users
  dependency:
    from_source: companies
    field: universalName
  input_key: company
  input_template:
    keywords: "engineering manager"
    company: "{value}"
    count: 50
  parallel: 2""",
        ],
    ),
    # ------------------------------------------------------------------
    # chains
    # ------------------------------------------------------------------
    "chains": GuideSection(
        title="Common Dependency Chains",
        description="Ready-to-use dependency configs for popular endpoint combinations",
        content="""\
These are the most common source dependency patterns. Always verify field
paths with `anysite describe <endpoint>` before using.

SEARCH → PROFILES:
Extract profile URNs from search results, fetch full profiles.

    - id: profiles
      endpoint: /api/linkedin/user
      dependency:
        from_source: search_results   # parent: /api/linkedin/search/users
        field: urn.value              # profile URN
        dedupe: true
      input_key: user
      parallel: 5

PROFILES → POSTS:
Get posts authored by collected profiles.

    - id: posts
      endpoint: /api/linkedin/user/posts
      dependency:
        from_source: profiles         # parent: /api/linkedin/user
        field: urn.value              # profile URN
      input_key: urn
      parallel: 3

POSTS → COMMENTS:
Get comments on collected posts.

    - id: comments
      endpoint: /api/linkedin/post/comments
      dependency:
        from_source: posts            # parent: /api/linkedin/user/posts
        field: urn.value              # post activity URN
      input_key: urn
      parallel: 5

POSTS → AUTHOR PROFILES (reverse lookup):
Get full profiles of post authors. Use author.urn.value, NOT urn.value.

    # COMMON MISTAKE: urn.value is the POST URN, not the author URN
    - id: author_profiles
      endpoint: /api/linkedin/user
      dependency:
        from_source: posts            # parent: /api/linkedin/user/posts
        field: author.urn.value       # AUTHOR's profile URN
        dedupe: true
      input_key: user
      parallel: 5

PROFILES → COMPANIES:
Get companies where profiles work. Uses company.universalName.

    - id: companies
      endpoint: /api/linkedin/company
      dependency:
        from_source: profiles         # parent: /api/linkedin/user
        field: company.universalName  # company slug (e.g., "microsoft")
        dedupe: true
      input_key: company
      parallel: 3

COMPANIES → COMPANY POSTS:
Get posts from company pages.

    - id: company_posts
      endpoint: /api/linkedin/company/posts
      dependency:
        from_source: companies        # parent: /api/linkedin/company
        field: universalName
        dedupe: true
      input_key: company
      input_template:
        company: "{value}"
        count: 20
      parallel: 3

COMPANIES → EMPLOYEES:
Search employees at companies. Requires input_template with array format.

    - id: employees
      endpoint: /api/linkedin/company/employees
      dependency:
        from_source: companies        # parent: /api/linkedin/company
        field: urn.value              # company URN
      input_key: companies
      input_template:
        companies:
          - type: company
            value: "{value}"
        count: 5
      parallel: 2

QUICK REFERENCE TABLE:

    Parent endpoint              → Child endpoint              field              input_key
    /api/linkedin/search/users   → /api/linkedin/user          urn.value          user
    /api/linkedin/user           → /api/linkedin/user/posts    urn.value          urn
    /api/linkedin/user/posts     → /api/linkedin/post/comments urn.value          urn
    /api/linkedin/user/posts     → /api/linkedin/user (author) author.urn.value   user
    /api/linkedin/user           → /api/linkedin/company       company.universalName  company
    /api/linkedin/company        → /api/linkedin/company/posts universalName      company (template)
    /api/linkedin/company        → /api/linkedin/company/employees  urn.value     companies (template)
""",
        examples=[
            """\
# Full chain: search → profiles → posts → comments
sources:
  - id: search
    endpoint: /api/linkedin/search/users
    params: { keywords: "CTO", count: 50 }
  - id: profiles
    endpoint: /api/linkedin/user
    dependency: { from_source: search, field: urn.value, dedupe: true }
    input_key: user
    parallel: 5
  - id: posts
    endpoint: /api/linkedin/user/posts
    dependency: { from_source: profiles, field: urn.value }
    input_key: urn
    parallel: 3
  - id: comments
    endpoint: /api/linkedin/post/comments
    dependency: { from_source: posts, field: urn.value }
    input_key: urn
    parallel: 5""",
        ],
    ),
    # ------------------------------------------------------------------
    # fields_matrix
    # ------------------------------------------------------------------
    "fields_matrix": GuideSection(
        title="Required Fields by Source Type",
        description="Which fields are required, optional, or unavailable for each source type",
        content="""\
Three source types have different field requirements:

TYPE: API (default — type can be omitted)
  Required:  id, endpoint
  Optional:  params, input_key, input_template, from_file, file_field,
             dependency, parallel, rate_limit, on_error, refresh,
             filter, llm, transform, export, db_load

TYPE: LLM (type: llm)
  Required:  id, type: llm, dependency (parent source), llm (>= 1 step)
  Optional:  filter, transform, export, db_load, refresh
  N/A:       endpoint, params, input_key, input_template, from_file,
             file_field, parallel, rate_limit, on_error

TYPE: UNION (type: union)
  Required:  id, type: union, sources (list of parent IDs)
  Optional:  dedupe_by, dependency, filter, llm, transform, export,
             db_load, refresh
  N/A:       endpoint, params, input_key, input_template, from_file,
             file_field, parallel, rate_limit, on_error

DEFAULTS:
  parallel:          1
  on_error:          "skip"
  refresh:           "auto"
  storage.path:      "./data/"
  db_load.exclude:   ["_input_value", "_parent_source"]
  db_load.sync:      "full"
  summarize max_length: 100 (words)

IMPORTANT NOTES:
  - `type` defaults to "api" when omitted
  - `dependency.field` is optional (needed for value extraction, not for LLM sources)
  - `endpoint` must start with `/` (e.g., `/api/linkedin/user`)
  - `categories` in classify steps is a comma-separated STRING, not an array
  - `partition_by` in storage is accepted but not currently used —
    layout is always `raw/<source_id>/<date>.parquet`
""",
        examples=[
            """\
# Minimal api source (type defaults to "api")
- id: search
  endpoint: /api/linkedin/search/users
  params: { keywords: "engineer", count: 50 }""",
            """\
# Minimal llm source
- id: analyzed
  type: llm
  dependency: { from_source: profiles }
  llm:
    - type: classify
      categories: "senior,mid,junior"
      output_column: level""",
            """\
# Minimal union source
- id: all_results
  type: union
  sources: [search_sf, search_ny]
  dedupe_by: urn.value""",
        ],
    ),
    # ------------------------------------------------------------------
    # llm
    # ------------------------------------------------------------------
    "llm": GuideSection(
        title="LLM Enrichment",
        description="Per-source LLM processing steps applied after API collection",
        content="""\
The `llm` list on a source defines LLM enrichment steps that run in order
after API data collection but before Parquet write. Enriched fields are stored
alongside raw data in Parquet and flow through to DB loading and exports.

Skip all LLM steps with `--no-llm` flag on `anysite dataset collect`.

STEP TYPES:

1. CLASSIFY -- categorize records into predefined or auto-detected categories

    llm:
      - type: classify
        categories: "positive,negative,neutral"   # explicit categories
        fields: [text, headline]                   # record fields to analyze
        output_column: sentiment                   # output column name

   Omit `categories` for auto-detection:

    llm:
      - type: classify
        fields: [text]
        output_column: topic

2. ENRICH -- extract structured attributes using `add` specs

    llm:
      - type: enrich
        add:
          - "sentiment:positive/negative/neutral"    # enum values
          - "score:1-10"                             # integer range
          - "language:string"                        # free-form string
          - "is_hiring:boolean"                      # boolean
          - "years_experience:integer"               # integer
        fields: [headline, about, experience]

   Add spec format: "field_name:type_or_values"
   Types: string, integer, boolean, or slash-separated enum values.
   Ranges like "1-10" generate integer constraints.

   Structured alternative (EnrichFieldSpec) — use objects instead of strings:

    llm:
      - type: enrich
        add:
          - name: sentiment
            values: [positive, negative, neutral]
          - name: score
            type: integer
            min: 1
            max: 10
          - name: language
            type: string
          - name: is_hiring
            type: boolean

   Both string and structured formats can be mixed in the same ``add`` list.

3. SUMMARIZE -- generate concise text summaries

    llm:
      - type: summarize
        fields: [about, experience, skills]
        output_column: profile_summary
        max_length: 100                  # max words (default: 100)

4. GENERATE -- free-form text from prompt templates

    llm:
      - type: generate
        prompt: "Write a one-paragraph recruiting intro for {name} who works as {headline} at {company}."
        output_column: intro_text
        temperature: 0.7

   Use `{field_name}` placeholders in the prompt. They are replaced with
   actual record values before sending to the LLM.

COMMON FIELDS (available on all step types):
  provider:      str   LLM provider override ("openai" or "anthropic")
  model:         str   Model ID override (e.g., "gpt-4o", "claude-sonnet-4-20250514")
  temperature:   float Temperature override (0.0-2.0)
  max_tokens:    int   Max response tokens override
  fields:        list  Record fields to include in LLM prompt (empty = all)
  output_column: str   Name of the output column (defaults depend on type)

MULTIPLE STEPS:
Steps run in order. Output from earlier steps is available to later steps:

    llm:
      - type: classify
        categories: "technical,business,personal"
        fields: [text]
        output_column: post_type
      - type: enrich
        add:
          - "sentiment:positive/negative/neutral"
          - "engagement_potential:1-10"
        fields: [text]
      - type: summarize
        fields: [text]
        output_column: summary

LLM-ONLY SOURCES (type: llm):
For processing without API calls, use `type: llm`:

    - id: enriched_profiles
      type: llm
      dependency:
        from_source: profiles
      llm:
        - type: enrich
          add:
            - "seniority:junior/mid/senior/staff/principal"
          fields: [headline, about]

LLM CONFIGURATION:
LLM providers are configured via `anysite llm setup` which stores keys in
`~/.anysite/config.yaml`. The `provider` and `model` fields on each step
override the default config.

CACHING:
LLM responses are cached in SQLite (~/.anysite/llm_cache.db). Re-running
collection on the same data doesn't re-call the LLM provider — cached
results are reused. Clear with `anysite llm cache-clear`.
""",
        examples=[
            """\
# Classify posts by topic with auto-detection
llm:
  - type: classify
    fields: [text]
    output_column: topic""",
            """\
# Full enrichment pipeline
llm:
  - type: classify
    categories: "hiring,product,thought_leadership,personal"
    fields: [text]
    output_column: post_type
  - type: enrich
    add:
      - "sentiment:positive/negative/neutral"
      - "engagement_potential:1-10"
      - "topics:string"
    fields: [text]
  - type: summarize
    fields: [text]
    output_column: summary""",
            """\
# Generate personalized outreach
llm:
  - type: generate
    prompt: "Write a brief, personalized recruiting message for {name} based on their experience as {headline}. Mention their work at {company}."
    output_column: outreach_message
    temperature: 0.7
    model: gpt-4o""",
        ],
    ),
    # ------------------------------------------------------------------
    # transform
    # ------------------------------------------------------------------
    "transform": GuideSection(
        title="Filtering & Transforms",
        description="Three-level filtering: source-level, export, and database loading",
        content="""\
The pipeline supports filtering at three independent stages:

  Collection -> [source.filter] -> LLM -> Parquet -> [transform.filter] -> Export
                                                      [db_load.filter]  -> DB

LEVEL 1 - SOURCE FILTER (source.filter):
Applied AFTER collection, BEFORE LLM enrichment and Parquet write.
Records that don't match are dropped entirely from the source.
Use this to avoid wasting LLM tokens on irrelevant records.

    - id: comments
      endpoint: /api/linkedin/post/comments
      filter: ".is_commenter_post_author == false"
      llm:
        - type: enrich
          add: ["score:1-10"]

LEVEL 2 - TRANSFORM FILTER (transform.filter):
Applied AFTER Parquet write, BEFORE exports only.
Full records are preserved in Parquet for dependency resolution.

    transform:
      filter: ".score > 5"

LEVEL 3 - DB LOAD FILTER (db_load.filter):
Applied when loading records into a relational database.
Only affects which records enter the DB; Parquet is unchanged.

    db_load:
      filter: ".active == true"
      fields: [name, score]

FILTER SYNTAX:
Safe expression parser (no eval). Use `.field` prefix for record fields.

Operators: ==, !=, >, <, >=, <=
Combinators: and, or
Types: numbers, strings, booleans (true/false), null

    filter: ".follower_count > 1000 and .status == \"active\""
    filter: ".is_author == false"
    filter: ".name != null"
    filter: ".score > 5 or .category == \"priority\""

Boolean comparison also works with 0/1 integer values:
    filter: ".is_author == false"    # matches both False and 0

TRANSFORM - FIELDS:
Select and rename fields. Supports dot-notation with aliases:

    transform:
      fields:
        - name
        - headline
        - "urn.value AS urn_id"       # extract nested + rename
        - "company.name AS company"
        - follower_count

TRANSFORM - ADD_COLUMNS:
Inject static values into every exported record:

    transform:
      add_columns:
        batch: "q1-2026"
        source: "linkedin"

COMBINING ALL THREE LEVELS:

    - id: comments_analyzed
      type: llm
      dependency:
        from_source: comments
        field: urn.value
      filter: ".is_commenter_post_author == false"   # Level 1
      llm:
        - type: enrich
          add: ["score:1-10", "is_llm:boolean"]
      transform:
        filter: ".score > 5"                          # Level 2
        fields: [text, author, score]
      db_load:
        filter: ".is_llm == true"                     # Level 3
        fields: [text, author, score, is_llm]
""",
        examples=[
            """\
# Source filter: skip author's own comments before LLM
- id: analyzed
  type: llm
  dependency:
    from_source: comments
    field: urn.value
  filter: ".is_commenter_post_author == false"
  llm:
    - type: enrich
      add: ["score:1-10"]""",
            """\
# Three-level filtering
- id: profiles
  endpoint: /api/linkedin/search/users
  filter: ".follower_count > 100"             # drop low-engagement before LLM
  llm:
    - type: classify
      categories: "candidate,recruiter,other"
  transform:
    filter: ".category == \"candidate\""       # export only candidates
    fields: [name, headline, category]
  db_load:
    filter: ".category_confidence > 0.8"       # only high-confidence to DB
    fields: [name, headline, category]
""",
        ],
    ),
    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    "export": GuideSection(
        title="Exports",
        description="Per-source export destinations (file and webhook)",
        content="""\
The optional `export` list on a source defines where records are sent AFTER
Parquet write. If a `transform` block is present, transformed records are
exported. Multiple export destinations per source are supported.

FILE EXPORT:
Write records to a local file in JSON, JSONL, or CSV format.

    export:
      - type: file
        format: jsonl                       # json, jsonl, or csv
        path: "./output/profiles_{{date}}.jsonl"

Path templates:
  {{date}}     -- collection date (YYYY-MM-DD)
  {{source}}   -- source ID
  {{dataset}}  -- dataset name

    export:
      - type: file
        format: csv
        path: "./output/{{dataset}}/{{source}}_{{date}}.csv"

WEBHOOK EXPORT:
POST records to an HTTP endpoint. Records are sent as a JSON array in the
request body.

    export:
      - type: webhook
        url: https://api.example.com/ingest
        headers:
          Authorization: "Bearer ${API_TOKEN}"
          Content-Type: "application/json"

Environment variable references (${VAR}) in headers are expanded at runtime.

MULTIPLE EXPORTS:

    export:
      - type: file
        format: csv
        path: "./reports/{{date}}.csv"
      - type: file
        format: jsonl
        path: "./raw/{{source}}_{{date}}.jsonl"
      - type: webhook
        url: https://hooks.example.com/data
""",
        examples=[
            """\
# Export to JSONL file
export:
  - type: file
    format: jsonl
    path: "./output/{{source}}_{{date}}.jsonl" """,
            """\
# Export to webhook with auth header
export:
  - type: webhook
    url: https://api.example.com/data
    headers:
      Authorization: "Bearer ${API_TOKEN}"
      X-Source: "anysite"
""",
        ],
    ),
    # ------------------------------------------------------------------
    # db_load
    # ------------------------------------------------------------------
    "db_load": GuideSection(
        title="Database Loading",
        description="Per-source config for loading data into a relational database",
        content="""\
The optional `db_load` block on a source configures how records are loaded
into a relational database via `anysite dataset load-db` or the `--load-db`
flag on `anysite dataset collect`.

BASIC USAGE:

    db_load:
      table: candidates              # custom table name (default: source_id)

FIELD SELECTION:
Select and rename fields using dot-notation. Unselected fields are excluded.

    db_load:
      table: candidates
      fields:
        - name
        - headline
        - "urn.value AS urn_id"      # extract nested value + rename column
        - "company.name AS company"
        - follower_count
        - job_status                 # from LLM enrichment

FIELD EXCLUSION:
Exclude specific fields (default: _input_value, _parent_source):

    db_load:
      exclude:
        - _input_value
        - _parent_source
        - raw_html

FILTER:
Filter records before loading into the database. Uses the same safe expression
syntax as source.filter and transform.filter. Parquet data is unchanged.

    db_load:
      filter: ".active == true and .score > 5"
      table: high_score
      fields: [name, score]

DIFF-BASED INCREMENTAL SYNC:
When `key` is set and the table already has data from 2+ snapshots, the
loader diffs the two most recent snapshots and applies only the changes
(INSERT new, DELETE removed, UPDATE changed records).

    db_load:
      table: candidates
      key: urn.value                 # unique identifier for diff matching
      sync: full                     # full (default): INSERT+DELETE+UPDATE
                                     # append: INSERT only (keeps old records)

FK LINKING:
When loading dependent sources, the loader automatically creates foreign key
columns linking child records to parent records. This uses the `_input_value`
provenance field to match parent-child relationships.

    # Parent source "profiles" loads into table "profiles"
    # Child source "posts" depends on "profiles"
    # -> "posts" table gets a "profiles_id" column with FK to profiles.id

LOADING COMMANDS:

    # Load all sources into database
    anysite dataset load-db dataset.yaml -c mydb

    # Load specific source
    anysite dataset load-db dataset.yaml -c mydb --source profiles

    # Drop and recreate tables
    anysite dataset load-db dataset.yaml -c mydb --drop-existing

    # Load a specific snapshot date
    anysite dataset load-db dataset.yaml -c mydb --snapshot 2026-01-15

    # Collect and load in one step
    anysite dataset collect dataset.yaml --load-db mydb

SCHEMA INFERENCE:
Table schemas are auto-inferred from record data. Detected types include:
integer, float, boolean, date, datetime, url, email, json, varchar, text.
Each table gets an auto-increment `id` primary key.
""",
        examples=[
            """\
# Basic db_load with field selection
db_load:
  table: candidates
  key: urn.value
  fields:
    - name
    - headline
    - "urn.value AS urn_id"
    - job_status
    - years_experience""",
            """\
# Append-only sync (never delete old records)
db_load:
  table: events
  key: event_id
  sync: append
  exclude: [_input_value, _parent_source, raw_data]
""",
        ],
    ),
    # ------------------------------------------------------------------
    # storage
    # ------------------------------------------------------------------
    "storage": GuideSection(
        title="Storage",
        description="Storage configuration for collected data",
        content="""\
The `storage` block configures where and how collected data is persisted.

    storage:
      format: parquet                          # only option currently
      path: ./data/my-dataset/                 # base directory
      partition_by: [source_id, collected_date] # partitioning scheme

FORMAT:
Currently only `parquet` is supported. Apache Parquet provides efficient
columnar storage with compression, ideal for analytical queries via DuckDB.

PATH:
Relative paths are resolved against the directory containing the YAML config
file. Absolute paths are used as-is.

PARTITION_BY:
Controls the directory layout. Default: [source_id, collected_date].

STORAGE LAYOUT:
Data is stored in this directory structure:

    <path>/
      raw/
        <source_id>/
          <YYYY-MM-DD>.parquet     # one file per collection date
          <YYYY-MM-DD>.parquet
        <source_id>/
          <YYYY-MM-DD>.parquet
      metadata.json                # incremental state, source info

Each collection run creates or overwrites the Parquet file for that date.
Multiple snapshots accumulate over time for diff analysis and history.

METADATA:
The `metadata.json` file tracks:
  - Last collection date per source
  - Record counts per source
  - Collected input values (for incremental deduplication)
""",
        examples=[
            """\
storage:
  format: parquet
  path: ./data/recruiting-pipeline/
  partition_by: [source_id, collected_date]""",
            """\
# Absolute path
storage:
  format: parquet
  path: /data/datasets/linkedin/
  partition_by: [source_id, collected_date]
""",
        ],
    ),
    # ------------------------------------------------------------------
    # schedule
    # ------------------------------------------------------------------
    "schedule": GuideSection(
        title="Scheduling",
        description="Cron-based scheduling for automated data collection",
        content="""\
The optional `schedule` block defines a cron expression for automated
collection. The schedule is used by `anysite dataset schedule` to generate
crontab entries or systemd timer units.

CONFIG:

    schedule:
      cron: "0 6 * * 1"            # every Monday at 6am
      # cron: "0 */4 * * *"        # every 4 hours
      # cron: "0 9 * * MON-FRI"    # weekdays at 9am
      # cron: "30 2 1 * *"         # 1st of each month at 2:30am

GENERATING CRONTAB:

    anysite dataset schedule dataset.yaml
    anysite dataset schedule dataset.yaml --incremental
    anysite dataset schedule dataset.yaml --incremental --load-db pg

Output example:
    0 6 * * 1 anysite dataset collect /path/to/dataset.yaml --incremental --load-db pg

GENERATING SYSTEMD UNITS:

    anysite dataset schedule dataset.yaml --systemd
    anysite dataset schedule dataset.yaml --systemd --incremental --load-db pg

Generates two files:
  - anysite-<dataset-name>.timer   (timer unit with OnCalendar)
  - anysite-<dataset-name>.service (service unit with ExecStart)

RECOMMENDED PATTERN:
Use `--incremental` with `--load-db` for production pipelines:

    schedule:
      cron: "0 6 * * 1"

    # Then generate and install:
    anysite dataset schedule dataset.yaml --incremental --load-db mydb
""",
        examples=[
            """\
schedule:
  cron: "0 6 * * 1"   # every Monday at 6am""",
            """\
schedule:
  cron: "0 */6 * * *"  # every 6 hours
""",
        ],
    ),
    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    "notifications": GuideSection(
        title="Notifications",
        description="Webhook notifications triggered after collection runs",
        content="""\
The optional `notifications` block defines webhook URLs that receive POST
requests when collection completes or fails.

    notifications:
      on_complete:
        - url: https://hooks.slack.com/services/T00/B00/xxxx
        - url: https://api.example.com/webhooks/pipeline-done
          headers:
            Authorization: "Bearer ${WEBHOOK_TOKEN}"
      on_failure:
        - url: https://hooks.slack.com/services/T00/B00/yyyy

PAYLOAD:
The webhook receives a JSON POST body with run details:
  - dataset_name: name of the dataset
  - status: "success" or "failed"
  - record_count: total records collected
  - source_count: number of sources processed
  - duration: collection time in seconds
  - error: error message (for failures)

HEADERS:
Custom headers can be set per webhook. Environment variable references
(${VAR}) are expanded at runtime.

USE CASES:
  - Slack/Teams notifications for pipeline monitoring
  - Trigger downstream processing via webhooks
  - Alert on-call when pipelines fail
""",
        examples=[
            """\
notifications:
  on_complete:
    - url: https://hooks.slack.com/services/T00/B00/xxxx
  on_failure:
    - url: https://hooks.slack.com/services/T00/B00/yyyy""",
        ],
    ),
    # ------------------------------------------------------------------
    # incremental
    # ------------------------------------------------------------------
    "incremental": GuideSection(
        title="Incremental Collection",
        description="How to collect only new data on subsequent runs",
        content="""\
Incremental collection skips input values that have already been collected,
avoiding redundant API calls and reducing costs.

USAGE:

    anysite dataset collect dataset.yaml --incremental

HOW IT WORKS:
The `MetadataStore` tracks which input values have been collected per source
in `metadata.json` (under the `collected_inputs` key). On incremental runs:

  - Independent sources: always re-collected (they have no input values)
  - From_file sources: skip values already in collected_inputs
  - Dependent sources: skip values already in collected_inputs
  - Union sources: always re-created from parents

REFRESH MODES (per source):

    refresh: auto       # (default) use incremental caching
    refresh: always     # re-collect every run, ignore cache

Use `refresh: always` for sources where data changes frequently and you want
fresh data on every run (e.g., user activity feeds, search results).

RESETTING STATE:

    # Reset all sources
    anysite dataset reset-cursor dataset.yaml

    # Reset a specific source
    anysite dataset reset-cursor dataset.yaml --source profiles

This clears the `collected_inputs` in `metadata.json`, causing the next
incremental run to re-collect everything.

RECOMMENDED PATTERN:
Combine incremental collection with scheduling and DB loading:

    anysite dataset collect dataset.yaml --incremental --load-db mydb

With `db_load.key` set, the DB loader performs diff-based sync, updating
only changed records in the database.
""",
        examples=[
            """\
# Collect only new data
anysite dataset collect dataset.yaml --incremental

# Reset and re-collect everything
anysite dataset reset-cursor dataset.yaml
anysite dataset collect dataset.yaml""",
            """\
# Source that always refreshes
- id: activity_feed
  endpoint: /api/linkedin/user/posts
  from_file: users.txt
  input_key: user
  refresh: always        # ignore incremental cache
  parallel: 3
""",
        ],
    ),
    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    "validation": GuideSection(
        title="Validation",
        description="Fast config validation without running collection",
        content="""\
The `anysite dataset validate` command checks a dataset YAML config for
errors without making any API calls or running collection. It finishes in
under 0.1 seconds and is useful for CI pipelines and pre-commit checks.

USAGE:

    anysite dataset validate dataset.yaml
    anysite dataset validate dataset.yaml --json

WHAT IS CHECKED:
  - YAML syntax and Pydantic model validation
  - Discriminated union source types (api, llm, union)
  - Dependency graph (topological sort, missing references, cycles)
  - All filter expressions (source.filter, transform.filter, db_load.filter)
  - LLM add specs (both string and structured EnrichFieldSpec formats)

FILTER DIAGNOSTICS:
The validator detects common filter typos and suggests corrections:
  - `=` instead of `==` ("did you mean '=='?")
  - `&&` instead of `and` ("did you mean 'and'?")
  - `||` instead of `or` ("did you mean 'or'?")
  - `!` instead of `!=` ("did you mean '!='?")

JSON OUTPUT:
With `--json`, returns a structured result for machine consumption:

    {
      "ok": true,
      "result": {
        "valid": true,
        "errors": [],
        "warnings": ["sources[0]: parallel=20 is high, consider 3-5"]
      }
    }
""",
        examples=[
            """\
# Quick validation
anysite dataset validate dataset.yaml

# JSON output for CI
anysite dataset validate dataset.yaml --json""",
        ],
    ),
    # ------------------------------------------------------------------
    # mistakes
    # ------------------------------------------------------------------
    "mistakes": GuideSection(
        title="Common Mistakes",
        description="Frequent errors when building dataset configs and how to fix them",
        content="""\
1. WRONG DEPENDENCY FIELD PATH
   Using the record's own URN instead of the related entity's URN.

   WRONG: field: urn.value         # This is the POST's URN
   RIGHT: field: author.urn.value  # This is the post AUTHOR's profile URN

   Fix: Run `anysite describe <parent_endpoint>` and check output fields
   to find the correct path to the value you need.

2. MISSING {value} IN input_template
   Static template without placeholder — same value for every request.

   WRONG:
     input_template:
       company: "microsoft"       # Static! Same for every request

   RIGHT:
     input_template:
       company: "{value}"         # Dynamic — replaced with extracted value

3. ENDPOINT WITHOUT LEADING SLASH

   WRONG: endpoint: api/linkedin/user
   RIGHT: endpoint: /api/linkedin/user

4. CATEGORIES AS ARRAY INSTEAD OF STRING

   WRONG: categories: ["positive", "negative", "neutral"]
   RIGHT: categories: "positive,negative,neutral"

5. PARALLEL TOO HIGH
   Setting parallel: 50+ causes rate limiting and errors.

   WRONG: parallel: 50
   RIGHT: parallel: 3              # 3-5 is optimal for most endpoints

6. CONFUSING field AND input_key

   field:     extracts value FROM parent source records (dependency.field)
   input_key: puts value INTO the child API request parameter name

   Example: extract urn.value from parent, send as `user` param:

     dependency:
       from_source: search_results
       field: urn.value           # WHAT to extract from parent
     input_key: user              # WHERE to put it in API call

7. LLM SOURCE WITHOUT REQUIRED FIELDS

   WRONG:
     - id: enriched
       type: llm
       llm:
         - type: classify
           categories: "a,b"

   RIGHT:
     - id: enriched
       type: llm
       dependency:
         from_source: profiles    # Required for type: llm!
       llm:
         - type: classify
           categories: "a,b"

8. DUCKDB VIEW NAMES WITH SPECIAL CHARACTERS
   Source ID: search-results  → DuckDB view: search_results
   Source ID: user.posts      → DuckDB view: user_posts

   Hyphens and dots are replaced with underscores in view names.

9. LLM RESPONSES ARE CACHED
   LLM enrichment results are cached in SQLite (~/.anysite/llm_cache.db).
   Re-running collection with the same data won't re-call the LLM provider.
   Clear cache with: anysite llm cache-clear

10. VALIDATE CATCHES MOST ERRORS
    Always validate before collecting:

    anysite dataset validate dataset.yaml --json

    Common validate messages:
      "Endpoint must start with '/'"         → add leading /
      "enrich step requires 'add'"           → add 'add' list to enrich step
      "LLM source must have a dependency"    → add dependency block
      "did you mean '=='?"                   → replace = with == in filter
""",
        examples=[
            """\
# Validate → fix → collect workflow
anysite dataset validate dataset.yaml --json
# Fix any errors...
anysite dataset collect dataset.yaml --dry-run
anysite dataset collect dataset.yaml""",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Complete example configs
# ---------------------------------------------------------------------------

EXAMPLE_CONFIGS: dict[str, str] = {
    # ------------------------------------------------------------------
    "basic": """\
name: linkedin-search
description: Search for software engineers
sources:
  - id: search_results
    endpoint: /api/linkedin/search/users
    params:
      keywords: "software engineer"
      count: 50
storage:
  format: parquet
  path: ./data/linkedin-search/
  partition_by: [source_id, collected_date]""",
    # ------------------------------------------------------------------
    "advanced": """\
name: recruiting-pipeline
description: Multi-source recruiting pipeline with enrichment
sources:
  - id: search_sf
    endpoint: /api/linkedin/search/users
    params:
      keywords: "senior engineer"
      location: "San Francisco"
      count: 100

  - id: search_ny
    endpoint: /api/linkedin/search/users
    params:
      keywords: "senior engineer"
      location: "New York"
      count: 100

  - id: all_candidates
    type: union
    sources: [search_sf, search_ny]
    dedupe_by: urn.value

  - id: profiles
    endpoint: /api/linkedin/user
    dependency:
      from_source: all_candidates
      field: urn.value
      dedupe: true
    input_key: user
    parallel: 5
    llm:
      - type: classify
        categories: "active_seeker,passive,not_looking"
        fields: [headline, about]
        output_column: job_status
      - type: enrich
        add:
          - "years_experience:integer"
          - "primary_skill:string"
          - "seniority:junior/mid/senior/staff/principal"
        fields: [headline, about, experience]
    db_load:
      table: candidates
      key: urn.value
      fields:
        - name
        - headline
        - "urn.value AS urn_id"
        - job_status
        - years_experience
        - primary_skill
        - seniority

  - id: companies
    endpoint: /api/linkedin/company
    dependency:
      from_source: profiles
      field: company.universalName
      dedupe: true
    input_key: company
    parallel: 3
    db_load:
      table: companies
      key: universalName

storage:
  format: parquet
  path: ./data/recruiting/
  partition_by: [source_id, collected_date]

schedule:
  cron: "0 6 * * 1"

notifications:
  on_complete:
    - url: https://hooks.slack.com/services/xxx
  on_failure:
    - url: https://hooks.slack.com/services/xxx""",
    # ------------------------------------------------------------------
    "from_file": """\
name: company-research
description: Research companies from a list
sources:
  - id: companies
    endpoint: /api/linkedin/company
    from_file: companies.txt
    input_key: company
    parallel: 3
    export:
      - type: file
        format: jsonl
        path: "./output/companies_{{date}}.jsonl"

  - id: company_employees
    endpoint: /api/linkedin/search/users
    dependency:
      from_source: companies
      field: universalName
    input_key: company
    input_template:
      keywords: "CTO OR VP Engineering"
      company: "{value}"
    parallel: 2

storage:
  format: parquet
  path: ./data/company-research/
  partition_by: [source_id, collected_date]""",
    # ------------------------------------------------------------------
    "llm_enrichment": """\
name: content-analysis
description: Analyze LinkedIn posts with LLM
sources:
  - id: posts
    endpoint: /api/linkedin/user/posts
    from_file: influencers.txt
    input_key: user
    parallel: 2
    llm:
      - type: classify
        categories: "thought_leadership,hiring,product_launch,personal,industry_news"
        fields: [text]
        output_column: post_category
      - type: enrich
        add:
          - "sentiment:positive/negative/neutral"
          - "engagement_potential:1-10"
          - "topics:string"
        fields: [text]
      - type: summarize
        fields: [text]
        output_column: summary
    transform:
      filter: ".engagement_potential > 5"
      fields:
        - text
        - summary
        - post_category
        - sentiment
        - engagement_potential
        - topics
    export:
      - type: file
        format: csv
        path: "./output/high_engagement_{{date}}.csv"
      - type: webhook
        url: https://api.example.com/posts
        headers:
          Authorization: "Bearer ${API_TOKEN}"

storage:
  format: parquet
  path: ./data/content-analysis/
  partition_by: [source_id, collected_date]""",
    # ------------------------------------------------------------------
    "filter_levels": """\
name: comment-analysis
description: Three-level filtering — source, export, and DB
sources:
  - id: posts
    endpoint: /api/linkedin/user/posts
    from_file: authors.txt
    input_key: user
    parallel: 3

  - id: comments
    endpoint: /api/linkedin/post/comments
    dependency:
      from_source: posts
      field: urn.value
    input_key: urn
    parallel: 5

  - id: comments_analyzed
    type: llm
    dependency:
      from_source: comments
      field: urn.value
    filter: ".is_commenter_post_author == false"     # Level 1: skip author replies
    llm:
      - type: enrich
        add:
          - "llm_score:1-10"
          - "is_llm:boolean"
          - "explanation:string"
        fields: [text, author]
        temperature: 0.0
    transform:
      filter: ".llm_score > 5"                       # Level 2: export high-score only
      fields: [text, author, llm_score, is_llm, explanation]
    export:
      - type: file
        format: csv
        path: "./output/analyzed_comments_{{date}}.csv"
    db_load:
      filter: ".is_llm == true"                      # Level 3: only flagged to DB
      table: flagged_comments
      fields:
        - text
        - author
        - llm_score
        - is_llm
        - explanation

storage:
  format: parquet
  path: ./data/comment-analysis/
  partition_by: [source_id, collected_date]""",
}
