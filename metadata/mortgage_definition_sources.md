# Closed-end Mortgage Definition and Sources

Batch 1 defines the Mortgage segment as **closed-end loans secured by 1-4 family residential properties**, excluding revolving/open-end HELOC exposure. The definition follows the Proposal Appendix B and is applied consistently to the balance and RI-B net-charge-off numerator.

| Component | MDRMs | Treatment |
|---|---|---|
| Closed-end exposure | RCON5367/5368 from 2005Q1; RCFD5367/5368 from 2013Q2 | Sum both liens after coalescing the applicable domestic/consolidated reporting variant. |
| Closed-end charge-offs | RIADC234 (first lien), RIADC235 (junior lien) | Quarterize each YTD series, then sum. |
| Closed-end recoveries | RIADC217 (first lien), RIADC218 (junior lien) | Quarterize each YTD series, then sum. |
| Excluded open-end exposure | RCON/RCFD1797 | Do not map to Mortgage. |

The FFIEC MDRM/validation material identifies RCON1797 as revolving, open-end 1-4 family lending and identifies 5367/5368 as the closed-end first- and junior-lien components. The retained archives contain the RCON series throughout 2005Q1--2025Q4, while the RCFD consolidated series first appears in the 2013Q2 archive; the mapping therefore does not backdate RCFD5367/5368 to 2005. The Federal Reserve MDRM definitions for RIADC235 and RIADC218 identify them as the corresponding closed-end junior-lien RI-B charge-off and recovery items. The RI-B series support Mortgage NCO from the project start, so Mortgage NCO coverage remains 2005Q1--2025Q4.

Sources:

- [FFIEC validation information for RC-C closed-end and revolving 1-4 family items](https://www.ffiec.gov/PDF/FFIEC_forms/FFIEC031_041edits_200203.pdf)
- [Federal Reserve MDRM: RIADC235](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C235)
- [Federal Reserve MDRM: RIADC218](https://www.federalreserve.gov/apps/mdrm/data-dictionary/search/item?keyword=C218)
- [FFIEC 031/041 historical reporting materials](https://www.ffiec.gov/resources/reporting-forms/ffiec041)
