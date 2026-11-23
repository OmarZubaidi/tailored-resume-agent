# Write a cover letter for a job listing

You write a cover letter for one job listing, in the candidate's voice.

## Inputs

Job title: $job_title
Company: the hiring company named in the listing
Years as a software engineer (computed from the skills ledger; use this exact number): $years

### Job listing

$listing

### Tailored resume (facts you may use)

$resume

### Story notes (confirmed facts behind resume bullets; the only source for a story's context)

$stories

### Suggested template

$template

### Voice notes

$voice

## Shape

The letter adds what the resume cannot say. It is not a summary of the resume. Treat the template
as a suggestion of shape and tone, not a form to fill in, and leave no "[...]" placeholders.

1. Hook, one or two sentences. Connect one specific requirement or problem from the listing to the
   candidate's single most relevant proof point, and say what he enjoys about that kind of work.
   Never open with identity ("I'm a software engineer"), the act of applying, or enthusiasm.
2. One story, three or four sentences. Lead with the work itself, not a label for it ("The clearest
   example is..."). Prefer a story from the story notes; tell it as the constraint, what he did,
   and the result, using only what the notes and resume state. A story without notes opens with the
   result and states no constraint or context. Pick the story that fits this listing best. No list
   of projects, and name at most three technologies, only ones the listing also names.
3. Earlier career, two or three sentences. Use one concrete fact from the story notes that fits
   this listing, so the reader sees he understands users because he was one. Let the fact carry
   it; do not add a sentence explaining the lesson.
4. Why this company, one or two sentences, optional. Build on one concrete, non-generic detail the
   listing states, such as a product, customer, value or story. Never invent company details. If
   the listing offers nothing specific, leave this paragraph out.
5. Close, one plain sentence offering a conversation.

## Rules

1. If you state experience, say "$years years". Never use another number of years.
2. Use only facts from the tailored resume and the story notes. Never add numbers, tools, outcomes
   or context they do not state.
3. Never restate the listing back to the reader, and never write "that's the kind of X your
   posting describes" or "X builds Y, and that's the part I enjoy most".
4. A register between professional and conversational: plain, warm, first person, contractions
   allowed, no slang, chat shorthand or business jargon. Lean more casual for small product
   companies and more formal for health systems, payers and enterprises. At most one touch of
   personality.
5. Write like a person, not a language model:
   - Use normal capitalization: start every sentence with a capital letter and capitalize "I".
   - Use plain apostrophes and a plain hyphen, and keep the apostrophe in every contraction.
     Never use an en or em dash, and never use a colon in a sentence.
   - Never use these words or phrases: $banned_words.
   - Never use contrast framing such as "not just X, it's Y", "it's not X, it's Y" or
     "not only X, but Y".
   - Vary sentence openings. Never start three sentences in a row with "I".
   - No moral-of-the-story sentences: state a fact and stop, without a follow-up that explains
     what it taught him or why it matters.
6. Keep the whole letter under $max_words words.

## Output

Return only the letter in Markdown: the salutation, the body paragraphs separated by blank lines, and
the closing line ("Best,") last. No title, signature or contact details; those are added for you.
