# Academic Studio verification

Verified September 14, 2026.

- Full Python test suite: 175 passed. Coverage includes request validation, Ollama stream failures, retries, targeted weekly repairs, independent saved runs, restart recovery, exports, and the desktop bridge through a stub.
- JavaScript syntax check passed after the final refresh-message fix.
- Live `hachi-master:latest` output was exported through the HTTP download route and validated with `OBESyllabusPayload`. The result is `LAB_3/sample_output_syllabus_live.json`.
- The final saved run is `3ae73828250345719e4083ad0d1b23b1`: four COs, fourteen ordered weeks, all four COs referenced, midterm at Week 7 and final at Week 14. Its 39.7-second duration measures a continuation repairing one week from a saved full draft, not fresh generation of the entire syllabus.
- Desktop and 390px mobile browser previews were inspected with Week 11 expanded. Mobile document width equaled viewport width, with no horizontal overflow. The final assessment columns and cleared history error passed a second visual review.

The UI review and design documentation used general agents in place of unavailable specialized Impeccable roles. The mechanical design detector ran in degraded regex mode because its parser dependencies were unavailable. Final review disposition was `ship` for the two remaining UI fixes; this is not certification of every possible UI state.

The browser workflow was exercised directly; native window creation and Save As behavior were covered with a desktop bridge stub. Academic quality and official PO alignment still require human review. CPU-only generation can take several minutes.
