### JSON Rules

- Must be valid JSON (no trailing commas, no comments)
- All claims must match prose evaluation
- `supporting_evidence` must contain at most 3 items
- `evidence_basis` items should be short factual anchors
- `confidence` must be one of: LOW, MEDIUM, HIGH

## Failure Modes and Limitations

### Common Failure Modes

1. **Résumé summarization**: Listing projects chronologically instead of extracting behavioral patterns
2. **Over-indexing on stars/followers**: Treating GitHub metrics as quality proof
3. **Inferring leadership from weak evidence**: Assuming solo projects prove team ownership
4. **Ignoring stated limitations**: Treating partial evidence as complete
5. **Manufacturing confidence**: Making strong claims from weak evidence
6. **Confusing activity with execution**: Assuming many repos equals shipping ability

### Known Limitations

- **Private work invisible**: GitHub scraping excludes private repos
- **Bounded contribution windows**: Historical activity may be incomplete
- **Partial repo inspection**: Only a subset of repos receive code-level analysis
- **No interview data**: Cannot assess communication, culture fit, or interpersonal skills
- **No reference checks**: Cannot validate claims or assess reputation
- **Solo work bias**: Team collaboration signals are weak or missing

### When to Reduce Confidence

- Evidence is mostly GitHub-only (no LinkedIn, no resume, no interview)
- Only a small fraction of repos inspected at code level
- No external OSS contributions (limits ecosystem engagement assessment)
- No work history details (limits career ambition assessment)
- All evidence from solo projects (limits team ownership assessment)

## Implementation Notes

### Integration into Candidate Analysis Pipeline

1. **Input**: Scraped GitHub, LinkedIn, resume artifacts
2. **Processing**: LLM-based signal extraction using this framework
3. **Output**: Structured JSON + prose evaluation
4. **Downstream**: Founder review, interview decision, reference checks

### Quality Assurance

- Validate JSON schema before returning
- Ensure all claims in JSON match prose evaluation
- Verify `supporting_evidence` contains at most 3 items
- Check that `input_limitations_acknowledged` reflects actual gaps

### Calibration

- Review evaluations against hiring outcomes
- Adjust confidence thresholds based on false positive/negative rates
- Refine dimension definitions based on founder feedback

## Writing Style

Every sentence should answer:
> "What does this teach me about the person?"

Never answer:
> "What did they build?"

The founder can read the résumé for that. Your job is to extract the latent signals hiding behind the evidence.

Be sharp, compressed, and opinionated. But do not manufacture confidence.

---

**Version**: 1.0  
**Last Updated**: 2025-01-27  
**Maintained By**: Founder-Side Talent Evaluation System