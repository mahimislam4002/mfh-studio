# Portfolio SaaS CV/Resume template handoff

This package contains 10 intentionally different visual systems, each as a CV and resume pair. The HTML files are visual prototypes and integration references; they are not wired into the production Flask app.

## User flow to implement
1. Select CV or resume and a template.
2. Select regional convention (Europe/Europass, US, Asia) and output language. Keep these as content/format choices and do not silently change the chosen visual theme.
3. Preserve the original Magic Box text. Ask the OpenAI API to organize only facts supplied by the user into structured sections; never invent employers, dates, degrees, metrics, or credentials. If a key fact is missing, leave it blank or ask a follow-up.
4. Render the selected template with the structured content. CVs must repeat experience/education entries and flow to additional A4 pages as needed. Resumes should remain one A4 page by concise copy and layout-aware omission rules, never by shrinking text below readable size.
5. Show preview and allow editing before download.

## Current template contract
Use `template_manifest.json` for IDs, kind, descriptions, paths, and page policy. `sample_profile.json` is fictional preview data. Profile schema: name, role, email, phone, location, website, about, skills[], languages[], education[{title,institution,dates}], experience[{title,employer,dates,bullets[]}], awards[]. The HTML prototypes use inline CSS so each layout remains visibly independent. Convert to Jinja components while preserving each layout's distinct grid, photo scale, typography, dividers, color blocks, timeline, and section order.

## API / security
The existing `generate_cv` flow was still marked Coming Soon when this handoff was prepared. Implement server-side API calls only. Store the API key in environment configuration; never expose it in browser JavaScript. Validate and normalize model JSON against the schema, escape rendered text, and keep the user's original notes available for edits. Do not send the supplied personal data to third-party services except the configured model endpoint with user consent.

## Preview and files
Open `ALL_PREVIEWS.html` for all 20 designs. `templates/cv/` and `templates/resume/` hold implementation references; `previews/` contains standalone copies for review.
