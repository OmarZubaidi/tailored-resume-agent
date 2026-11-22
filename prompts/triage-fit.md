# Extract a job listing's hard requirements

Read one job listing and list what it requires. Do not judge the candidate.

## Job listing

$listing

## Rules

1. `company`: the hiring company's name as the listing writes it, not the job board or applicant
   tracking system hosting it. Null if the listing does not say.
2. `role`: the job title exactly as the listing writes it, without location or team suffixes.
3. `years_required`: the minimum years of professional experience the listing requires, as a whole
   number, or null if it states none. Use the lowest number if it gives a range.
4. `required_skills`: hard skills listed as required (languages, frameworks, tools, platforms,
   standards). Leave out "preferred", "nice to have" and "bonus" items. Use the listing's spelling.
5. `other_requirements`: required items that are not skills, such as a degree or a domain.

## Output

Return only JSON, no prose:

```json
{
  "company": "Acme Health",
  "role": "Senior Software Engineer",
  "years_required": 3,
  "required_skills": ["TypeScript", "React", "AWS"],
  "other_requirements": ["Bachelor's degree in Computer Science or equivalent experience"]
}
```
