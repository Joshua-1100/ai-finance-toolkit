# Retrieved Context — Pooled Commission Plan (ASC 340-40 analysis)

Backend: `tfidf`  |  Chunks indexed: 8  |  Top-k per question: 3

Each question below is answered *only* from the chunks listed under it. Chunk IDs are `<source>#S<section>.<window>` and scores are cosine similarity, so every assertion in the memorandum can be traced back to a specific passage of the plan document.

## Q1

> 1. MATERIAL RIGHT & AMORTIZATION PERIOD: Under ASC 340-40, evaluate whether the 15% renewal
> discount constitutes a "material right" for the customer. Based on this, should the capitalized
> pooled commission asset be amortized strictly over the initial 12-month contract term, or must
> it be amortized over a longer Estimated Period of Benefit (EPB)?

### `PooledCommissions.txt#S8.1` — 3. FUNDING MECHANISM & RENEWAL STRATIFICATION  (score 0.406)

The Pool is funded based on contract stratification rules to match the long-term economic
benefit of the SaaS subscription lifecycle: - INITIAL TERMS (Year 1): The Pool allocates an
amount equal to 3.5% of New Annual Recurring Revenue (New ARR) closed for the initial 12-month
contract period. - RENEWAL OPTIONS (Year 2+): Customers executing Year 1 contracts receive a
contractually guaranteed option to renew the Software Service for an additional 12-month period
at a 15% discount relative to the Year 1 list price. Because this renewal requires minimal sales
friction, the Pool for Renewal Contract Value (Renew ARR) is funded at a significantly reduced
rate of 0.5% of the renewed contract value.

### `PooledCommissions.txt#S7.1` — ADDENDUM  (score 0.178)

1. PURPOSE & OVERVIEW (SaaS Alignment) This addendum applies exclusively to the sale of SaaS
Subscription Licenses ("The Software Service") with a mandatory initial Term of twelve (12)
months. The plan establishes compensation parameters for both Initial Terms and subsequent
Renewal Option periods.

### `PooledCommissions.txt#S5.1` — 4. ALLOCATION AND DISBURSEMENT LOGIC  (score 0.150)

The accumulated Pool funds are not tied to any single, specific customer contract. Instead, the
total pool is aggregated at the end of the quarter and distributed to eligible participants
using a Hybrid Allocation Method: - Base Weighting (60% of the Pool): Distributed proportionally
based on each participant’s base salary relative to the total base payroll of the eligible
regional team. - Performance Weighting (40% of the Pool): Distributed based on individual
Management by Objectives (MBO) attainment scores, evaluated by regional leadership at the end of
the quarter.

## Q2

> 2. RENEWAL COMMISSION DISPROPORTION: Section 3 notes that initial commissions are funded at
> 3.5%, while renewal commissions are funded at 0.5%. Under ASC 340-40-25-4, is the renewal
> commission considered "commensurate with" the initial commission? How does this disproportion
> affect our ability to expense the commission over the 1-year contract life versus forcing a
> 3-to-5 year capitalization amortization schedule?

### `PooledCommissions.txt#S8.1` — 3. FUNDING MECHANISM & RENEWAL STRATIFICATION  (score 0.348)

The Pool is funded based on contract stratification rules to match the long-term economic
benefit of the SaaS subscription lifecycle: - INITIAL TERMS (Year 1): The Pool allocates an
amount equal to 3.5% of New Annual Recurring Revenue (New ARR) closed for the initial 12-month
contract period. - RENEWAL OPTIONS (Year 2+): Customers executing Year 1 contracts receive a
contractually guaranteed option to renew the Software Service for an additional 12-month period
at a 15% discount relative to the Year 1 list price. Because this renewal requires minimal sales
friction, the Pool for Renewal Contract Value (Renew ARR) is funded at a significantly reduced
rate of 0.5% of the renewed contract value.

### `PooledCommissions.txt#S7.1` — ADDENDUM  (score 0.196)

1. PURPOSE & OVERVIEW (SaaS Alignment) This addendum applies exclusively to the sale of SaaS
Subscription Licenses ("The Software Service") with a mandatory initial Term of twelve (12)
months. The plan establishes compensation parameters for both Initial Terms and subsequent
Renewal Option periods.

### `PooledCommissions.txt#S4.1` — 3. FUNDING MECHANISM OF THE POOL  (score 0.124)

The Pool is funded globally at the corporate level based on total New Annual Recurring Revenue
(New ARR) closed across the entire region during the quarter. - The Pool allocates an amount
equal to 3.5% of all regional New ARR generated during the quarter, provided the region achieves
at least 85% of its aggregate quarterly quota. - If regional quota attainment falls below 85%,
the pool is funded at 0%. - If regional quota attainment exceeds 100%, an accelerator multiplier
of 1.5x is applied to the pool funding rate (increasing the funding rate to 5.25% for all
revenue generated above the quota threshold).

## Q3

> 3. PRACTICAL EXPEDIENT ELIGIBILITY: Can we safely apply the ASC 340-40 practical expedient to
> expense these pooled commissions immediately since the initial contract term is exactly one
> year, or does the 15% renewal discount/material right disqualify us from using the expedient?

### `PooledCommissions.txt#S8.1` — 3. FUNDING MECHANISM & RENEWAL STRATIFICATION  (score 0.312)

The Pool is funded based on contract stratification rules to match the long-term economic
benefit of the SaaS subscription lifecycle: - INITIAL TERMS (Year 1): The Pool allocates an
amount equal to 3.5% of New Annual Recurring Revenue (New ARR) closed for the initial 12-month
contract period. - RENEWAL OPTIONS (Year 2+): Customers executing Year 1 contracts receive a
contractually guaranteed option to renew the Software Service for an additional 12-month period
at a 15% discount relative to the Year 1 list price. Because this renewal requires minimal sales
friction, the Pool for Renewal Contract Value (Renew ARR) is funded at a significantly reduced
rate of 0.5% of the renewed contract value.

### `PooledCommissions.txt#S7.1` — ADDENDUM  (score 0.180)

1. PURPOSE & OVERVIEW (SaaS Alignment) This addendum applies exclusively to the sale of SaaS
Subscription Licenses ("The Software Service") with a mandatory initial Term of twelve (12)
months. The plan establishes compensation parameters for both Initial Terms and subsequent
Renewal Option periods.

### `PooledCommissions.txt#S5.1` — 4. ALLOCATION AND DISBURSEMENT LOGIC  (score 0.135)

The accumulated Pool funds are not tied to any single, specific customer contract. Instead, the
total pool is aggregated at the end of the quarter and distributed to eligible participants
using a Hybrid Allocation Method: - Base Weighting (60% of the Pool): Distributed proportionally
based on each participant’s base salary relative to the total base payroll of the eligible
regional team. - Performance Weighting (40% of the Pool): Distributed based on individual
Management by Objectives (MBO) attainment scores, evaluated by regional leadership at the end of
the quarter.

## Q4

> 4. REVENUE ALLOCATION BALANCE: Draft the specific disclosure note text we would include in our
> financial statement footnotes to explain our amortization policy for this SaaS pooled commission
> asset.

### `PooledCommissions.txt#S5.1` — 4. ALLOCATION AND DISBURSEMENT LOGIC  (score 0.149)

The accumulated Pool funds are not tied to any single, specific customer contract. Instead, the
total pool is aggregated at the end of the quarter and distributed to eligible participants
using a Hybrid Allocation Method: - Base Weighting (60% of the Pool): Distributed proportionally
based on each participant’s base salary relative to the total base payroll of the eligible
regional team. - Performance Weighting (40% of the Pool): Distributed based on individual
Management by Objectives (MBO) attainment scores, evaluated by regional leadership at the end of
the quarter.

### `PooledCommissions.txt#S3.1` — 2. ELIGIBILITY & PARTICIPANTS  (score 0.131)

Eligible participants include Regional Account Executives (AEs), Sales Development
Representatives (SDRs), and Solutions Engineers assigned to the respective geographic territory.
To participate in a quarterly pool distribution, the employee must be active and in good
standing on the final business day of the applicable performance period.

### `PooledCommissions.txt#S8.1` — 3. FUNDING MECHANISM & RENEWAL STRATIFICATION  (score 0.128)

The Pool is funded based on contract stratification rules to match the long-term economic
benefit of the SaaS subscription lifecycle: - INITIAL TERMS (Year 1): The Pool allocates an
amount equal to 3.5% of New Annual Recurring Revenue (New ARR) closed for the initial 12-month
contract period. - RENEWAL OPTIONS (Year 2+): Customers executing Year 1 contracts receive a
contractually guaranteed option to renew the Software Service for an additional 12-month period
at a 15% discount relative to the Year 1 list price. Because this renewal requires minimal sales
friction, the Pool for Renewal Contract Value (Renew ARR) is funded at a significantly reduced
rate of 0.5% of the renewed contract value.
