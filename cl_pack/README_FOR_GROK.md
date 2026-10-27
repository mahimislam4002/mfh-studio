# Cover Letter feature handoff

Contains 10 distinct A4 cover letter layout prototypes, preview gallery, manifest, fictional sample profile and implementation brief. The HTML files are design references and are not connected to the website yet.

## Required website flow
1. Add a Cover Letter entry point with two destinations: **Template Gallery** and **My Cover Letters**. Keep the site's existing navigation and styling conventions.
2. Template Gallery shows all ten cover-letter previews as full-page thumbnails; clicking a card selects that template.
3. Before generation, collect employer/company name, hiring manager name (optional), job title, job description or posting URL/text (optional but useful), location/address (optional), date, and any extra note about tone or motivation. Let the user review the CV/resume source to use.
4. Build the draft from the signed-in user's saved CV/resume profile and selected job information. Use only factual skills, work history, achievements and education from that profile; do not invent details or claim experience that is absent. Tailor a concise, role-specific letter and avoid copying the resume verbatim. Ask a follow-up if required facts are missing.
5. Render into the selected template, show preview/edit controls, and save the completed letter under **My Cover Letters** with its source profile/template and employer/job details. Include download (PDF and/or existing supported formats).
6. In My Cover Letters, each saved letter has View, Edit, Duplicate and Delete actions. Edit should prefill company, employer, job title, job description, and additional fields. When the user changes employer/company/job information and chooses regenerate, reuse their CV/resume facts and rebuild only that letter. Preserve the old version or ask before replacing it; never mutate their base CV/resume. Allow manual edits after regeneration. This supports many applications without re-entering career history.

## Data and implementation
Manifest IDs are stable template keys. `sample_profile.json` is fictional preview data, not a default user profile. Suggested saved record fields: id, owner_id, template_id, source_profile_id/revision, company_name, employer_name, job_title, job_description, output_language, rendered_content, created_at, updated_at, version. Enforce user ownership for read/update/delete. Keep API keys server-side in environment configuration. Validate model output, escape text, and retain the user's original inputs.

Open `ALL_PREVIEWS.html` to inspect all 10 designs. `templates/` contains standalone implementation references and `previews/` copies for the gallery. Preserve each layout's distinct geometry, typography, colors, spacing, and contact/recipient placement.
