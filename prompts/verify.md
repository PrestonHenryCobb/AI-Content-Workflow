<!-- version: 2 -->
Build a fact pack for this case so a script writer can only use verified facts.

Case: {title} ({location}, {year})
Starting sources: {sources}

Rules:
- Research with web search and fetch. Use reputable sources only (official databases,
  court records, established news outlets). Never cite Reddit, forums, or YouTube.
- Produce 8–20 atomic claims. Each claim is one fact. Give every claim its citations
  with the URL and a short verbatim quote from that page that supports it.
- Aim for two independent sources per claim. Keep single-source claims only if important;
  the writer will attribute them ("according to ...").
- People: list every *human being* mentioned, with their role. Never list organizations,
  agencies, news outlets, websites or places as people. name_allowed=false for anyone never
  charged, anyone acquitted unless their acquittal is the point, minors, and family members.
- legal_status and active_trial must reflect the latest reporting you can find.
- agency_contact: the agency to contact with information (from official pages), or "n/a".
- Do not include graphic injury details.

Return JSON matching the schema.
