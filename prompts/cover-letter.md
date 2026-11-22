# Write a cover letter for a job listing

You write a cover letter for one job listing, in the candidate's voice. A template is provided as a
suggestion of tone and content, not a form to fill in.

## Inputs

Job title: $job_title
Company: the hiring company named in the listing
Years as a software engineer (computed from the skills ledger; use this exact number): $years

### Job listing

$listing

### Tailored resume (the only facts you may use)

$resume

### Suggested template

$template

### Voice notes

$voice

## Rules

1. Treat the template as a suggestion, not a structure. Choose and order the evidence for this
   listing. Lead with the work closest to what the role needs and drop what does not help. Leave
   no "[...]" placeholders in the output.
2. State experience as "$years years". Never use another number of years.
3. Use only facts from the tailored resume. Never add numbers, tools or outcomes it does not state.
4. Reference something specific about the company that the listing states, such as a story, value
   or product, and build on it. Never invent company details.
5. A register between professional and conversational: plain, warm, first person, contractions
   allowed, no slang or chat shorthand. At most one or two touches of personality, like
   "integrating a fax (yes, that fax!) REST API".
6. Write like a person, not a language model:
   - Use normal capitalization: start every sentence with a capital letter and capitalize "I".
   - Use plain apostrophes and a plain hyphen, and keep the apostrophe in every contraction.
     Never use an en or em dash, and never use a colon in a sentence.
   - Never use these words or phrases: $banned_words.
   - Never use contrast framing such as "not just X, it's Y", "it's not X, it's Y" or
     "not only X, but Y".
7. Keep the whole letter under $max_words words so it fits on one page.

## Output

Return only the letter in Markdown: the salutation, the body paragraphs separated by blank lines, and
the closing line ("Best,") last. No title, signature or contact details; those are added for you.
