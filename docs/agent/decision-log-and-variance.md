# Decision log, auditors, and variance

This repository's connection to three global disciplines. The disciplines
themselves live in user-level Kiro steering (`ai-agent-workflow`, in its
Parallel-by-default and Auditor Sub-Agent sections, and
`benchmark-and-evidence-standards`) and apply to every session, so this document
does not restate them. It records only what is specific to this repository: where
the decision log lives, which tier words to use, where the auditors and the
variance discipline hook into existing mechanisms, and the recurring task-type
checklists.

## 1. Decision log

Multi-step tasks (adding a pattern, a verification run, an IaC change) keep a
per-task record with three sections, separate from the implementation write-up.

```markdown
## Decisions
- <what was decided>: <why. evidence basis: measurement / documented / assumption>

## Rejected alternatives
- <what was rejected>: <why. could it return if the situation changes>

## Assumptions
- <taken as given without verifying>: <what breaks if it is wrong>
```

Placement in this repository:

- Agent material here is tracked under `docs/agent/`, so **the reusable template
  (this file) is tracked.** A per-task decision record is process metadata
  (rejected options, unverified assumptions, evidence basis), so it lives under
  **`.private/tasks/<task>/`**, which is gitignored (`.private/` is in
  `.gitignore`). This matches output-standards: review provenance stays out of
  published docs.
- If a task already has a record file (`plan.md`, `report.md`, `evidence-record.md`,
  `impl-note.md`), **append the three sections to it; do not add a second file.**
  Existing records under `.private/notes/` keep their names; do not rename them.
  The names already in use here are `*-verify-plan-*.md`, `*-readiness-report.md`,
  and `evidence-record.md` inside a dated run directory.

### Evidence tier words (match the existing vocabulary, do not add a fifth)

Verification work maps the Decisions evidence basis to the tier words this
repository already uses in its docs and gates. Do not import the prompt's
`field-observation` / `hypothesis`; this repository has no such tier.

| Decision basis | JA doc tag | EN doc tag | Notes prose | Meaning |
|---|---|---|---|---|
| measurement | `[実測]` | `[Tested]` | `verified` | Executed and confirmed on real infrastructure here |
| documented | `[文書]` | `[Documented]` | `documented` | Stated in AWS / NetApp docs, source URL included, not run here |
| assumption | `[未測定]` | `[Not measured]` | `open` | Not executed or out of scope; investigation date and scope included |

The legend lives in `docs/ja|en/atx-containerization-fsxn-derivation.md` and the
candidate-D records under `.private/notes/`. A claim that is only statically
checked (cfn-lint) is `verified` **for static validation only** and `open` for
real-environment behaviour; keep the two separate, the way
`candidate-d-verified-readiness-report.md` does.

## 2. Auditor signals

Before continuing, call an auditor when any of these appears:

- the same approach has failed twice,
- the same file has been re-edited three or more times,
- the same error message recurs within a multi-step task.

Which auditor: `semantic_reviewer` to re-examine the decisions,
`context-gatherer` to check whether the assumptions still match the
implementation. Hand it the decision-log sections and the change diff. Direct it
to **doubt, not reinforce**: which decisions rest on assumption, which rejected
alternative should return now, which unverified assumption would waste the work
if wrong. Do not create an automatic hook for this.

Connection in this repository: there is no evidence-ledger script or ADR
directory here, so the auditor reviews the `.private/tasks/<task>/` decision
record directly. The pre-commit review of anything public (docs, README, commit,
PR) is the persona review board's job (output-standards, the global persona
steering); keep it separate from the auditor.

## 3. Variance before effect

Before claiming a change moved a performance, throughput, latency, or cost
number, measure the run-to-run spread of the **unchanged** configuration first.
If the change's delta sits inside that spread it is noise, not an effect: say so,
or raise the repetition count until the delta clears the spread. A single-shot
"A is faster than B" gets the same treatment.

Connection in this repository: no performance number has been measured here yet
(S3 Access Point effective throughput is the open item V5 in the candidate-D
record). When the first measurement is taken, name repeated runs the way the
existing evidence directories do (`d-evidence-<date>` and
`d-evidence-<date>-run2`), so a baseline run and a re-measure are distinguishable
on disk, and record the unchanged-baseline spread alongside the changed number.

## 4. Recurring task-type checklists

Grow these one item at a time. A second failure of the same kind is the signal
that an item is missing, not that the operator was careless.

### Adding or changing a CloudFormation template

- [ ] `make cfn-lint` passes (exit 0; cfn-lint exits 4 on warnings, so fix them).
- [ ] FSx for ONTAP file system / SVM / volume stays an external reference; the
      template does not create it (all five templates here follow this).
- [ ] `params/<name>.example.json` added or updated with dummy values only;
      real `params/*.json` stays gitignored.
- [ ] JA and EN docs changed in the same commit with matching `##` counts.

### Running a verification (real infrastructure)

- [ ] AWS SSO session is current (`aws sso login` is the user's to run; the
      session expires in 24h).
- [ ] Baseline captured before the change (SVM/volume/LUN/backup/ENI counts into
      `raw/`), the way `d-evidence-*/raw/baseline-*.json` does.
- [ ] Runtime-dependent prerequisites pulled live, not filled from memory or a
      doc: service version support status and price tier (e.g.
      `aws eks describe-cluster-versions`, since a default version can be on
      extended support and priced higher), add-on / driver version compatibility
      (`describe-addon-versions`), and the AMI the driver's docs actually require
      (vendor pages can disagree; state what the run shows).
- [ ] Node-level setup that the template does not do is identified and has an
      owner: a CloudFormation template with no launch template / user data
      installs no NFS/iSCSI tools, no multipath blacklist for local (NVMe/EBS)
      devices, and starts no iscsid/multipathd. Plan to apply them per node (SSM
      Run Command works when the node role has `AmazonSSMManagedInstanceCore`)
      and reboot if the driver docs require it.
- [ ] Security-group reachability checked by reading the actual ENIs after
      deploy, not by assuming the template's source SG applies: confirm which SG
      the node ENI carries and whether the ports the data path and the storage
      management endpoint need are open on the target SG.
- [ ] Any artifact that teardown will destroy is exported to `raw/` **before**
      teardown; a claim loses `verified` if its evidence was torn down first.
- [ ] Teardown counts backups of the storage file system before and after
      deleting driver-created volumes, so only teardown-created backups are
      removed and the pre-existing ones are left alone.
- [ ] Teardown confirmed by re-reading state after a delay, not by the delete
      call's success response.
- [ ] Decision record's Decisions basis mapped to a tier word from the table
      above; `verified` used only where real-environment behaviour was observed.

### Measuring a performance / cost number

- [ ] Unchanged-baseline run-to-run spread measured first (section 3).
- [ ] Repetition count high enough that the reported delta clears the spread, or
      the number is labelled noise.
- [ ] Environment recorded with the number (region, config, throughput capacity,
      date), per `benchmark-and-evidence-standards`.
