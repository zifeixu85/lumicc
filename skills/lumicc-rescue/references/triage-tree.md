# Crisis Triage Tree

3 binary questions → 1 of 6 branches.

```
Q1: Platform notification in last 24h?
├── YES → check notification type
│   ├── Account warning / health drop → BRANCH A: account_warning
│   ├── Ad disapproved → BRANCH B: ad_disapproval
│   ├── Listing/ASIN suppressed → BRANCH C: listing_suppression
│   └── Other → BRANCH F: other_platform_event
│
└── NO → Q2

Q2: Made any change in last 48h?
├── YES → 
│   ├── Changed price → suspect pricing/cohort impact
│   ├── Changed listing → suspect ranking algorithm change
│   ├── Changed ad → suspect creative / audience shift
│   └── Changed inventory level → suspect "in stock" gating
│   → BRANCH D: self_inflicted
│
└── NO → Q3

Q3: Drop is on single SKU or store-wide?
├── Single SKU → BRANCH C-like: listing-level investigation
│
└── Store-wide → suspect external:
    ├── Competitor undercut → BRANCH E: price_war
    ├── Algorithm shift → BRANCH G: algorithm_shift
    └── Platform-wide issue → BRANCH H: ecosystem_event
```

## Branch dispatch

| Branch | Playbook | Typical resolution time |
|--------|----------|--------------------------|
| A: account_warning | `playbooks/account-warning.md` | 2-7 days |
| B: ad_disapproval | `playbooks/ad-disapproval.md` | 1-3 days |
| C: listing_suppression | `playbooks/listing-suppression.md` | 1-14 days |
| D: self_inflicted | revert + re-test | hours |
| E: price_war | `playbooks/price-war.md` | days |
| F/H: ecosystem | wait + appeal | 1-7 days |
| G: algorithm_shift | `playbooks/algorithm-shift.md` | 7-30 days |

## Decision quality safeguards

- If 2 branches tie, ask user to choose; never force.
- Log the chosen branch to events with reason.
- After 24h watchdog, if no improvement: escalate to next-most-likely branch.
- Never recommend account closure or platform migration in the first 7 days.
