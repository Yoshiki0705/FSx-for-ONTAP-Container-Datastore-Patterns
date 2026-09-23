# Containerization (ECS / EKS) Derivation and FSx for ONTAP Integration

**Purpose**: Determine, from primary sources, whether the Amazon FSx for NetApp ONTAP integration verified in this repository applies when VMware workloads are migrated to Amazon ECS / Amazon EKS via the AWS Transform containerization capability (announced May 2026). Organize the difference from the EC2 rehost path, Fargate availability, and the path for using FSx for ONTAP as a persistent volume (PV) / data store from containers after modernization.

**Last Updated**: 2026-09-22
**Status**: Literature research. No hands-on verification performed (unverified scope marked with [Unverified] throughout)

---

## 1. Conclusion

**Using FSx for ONTAP as persistent storage after containerization is possible, but it is not a feature of AWS Transform.** Two features must be understood separately.

| Question | Answer | Tier |
|---|---|---|
| Can AWS Transform containerization deploy to ECS / EKS? | Yes. It containerizes source code, publishes to Amazon ECR, and deploys to ECS or EKS | [Documented] |
| Can that deployment use Fargate? | The ECS deployment is documented as Fargate-capable (see 3.3). EKS depends on the generated Helm chart | [Documented] |
| Does containerization attach the FSx for ONTAP block integration verified in this repository? | **No.** That is an EC2-rehost-only feature of AWS Transform for migrations (MGN), a separate path from containerization | [Documented] |
| Does AWS Transform containerization configure FSx for ONTAP as a PV? | **No.** The containerization scope ends at Docker packaging and deployment. Persistent storage configuration is not among its outputs (see 3.4) | [Documented] |
| Can a modernized EKS workload use FSx for ONTAP as a PV? | Yes. But you introduce NetApp Trident (a CSI driver) separately, not via AWS Transform. NFS (file) is primary, iSCSI (block) is also possible | [Documented] |
| Can Fargate use FSx for ONTAP as a PV / data store? | **No.** EKS Fargate cannot run the CSI node pod (DaemonSet / privileged), and ECS Fargate cannot mount FSx (see 4) | [Documented] |

**Design implication**: "Containerization" and "FSx for ONTAP integration" do not combine into one workflow. It becomes two stages: containerize with AWS Transform, then introduce Trident on EKS (EC2 worker nodes) to configure the PV. Choosing Fargate rules out FSx for ONTAP. The two stand in a trade-off relationship.

---

## 2. Evidence Tiers

| Tag | Meaning |
|---|---|
| **[Verified]** | Actually executed and confirmed in this repository (source is an existing verification report) |
| **[Documented]** | Stated in AWS / NetApp official documentation. Source URL included. Does not imply hands-on confirmation |
| **[Unverified]** | Not executed and not corroborated by public information. Investigation date and scope included |

"No mention found in public documentation" is a fact about the state of the documentation, not about product behavior. [Unverified] items carry **when and where** the search was done.

---

## 3. Separating the Two AWS Transform Features

### 3.1 Scope of the containerization capability [Documented]

AWS Transform containerization takes **source code as input** to containerize it (announced 2026-05-11, source: [What's New](https://aws.amazon.com/about-aws/whats-new/2026/05/aws-transform-containerization/) / [Source code containerization](https://docs.aws.amazon.com/transform/latest/userguide/transform-containers.html)).

| Item | Content |
|---|---|
| Input | GitHub / Bitbucket / GitLab (via AWS CodeConnections) or .zip. Individual files ≤ 1 GB, total ≤ 8 GB |
| Processing | Source code analysis → Dockerfile generation → image build with CVE scanning → publish to ECR |
| Output (IaC) | Helm charts for EKS, Terraform modules for ECS. Generated with validation |
| Dependency resolution | AWS CodeArtifact (Maven / PyPI / npm) and private ECR base images can be specified as sources |
| Supported structures | monorepo / multi-repo. Documented as scaling to thousands of applications |
| Deployment targets | Amazon ECS or Amazon EKS |

**Stated exclusion**: Containerization is "for applications that are not yet containerized" and **does not support migrating already-containerized workloads**. Official documentation states that existing containers should use standard ECS / EKS deployment methods.

Containerization runs within a VMware migration job, either as a standalone workflow or as part of an end-to-end migration where a wave's strategy is set to `containerize`.

### 3.2 Supported source workload types [Documented]

Because containerization analyzes source code, the supported languages and frameworks define the range of source workloads. The .NET modernization scope is documented explicitly (source: [Modernizing .NET with AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)).

| Item | Content |
|---|---|
| Transform from | .NET Framework 3.5, .NET Core 3.1, .NET 5.x through .NET 10 |
| Transform to | .NET 8, .NET 10, .NET Standard (class libraries) |
| Languages | C#, VB.NET (preview) |
| Project types | Class libraries, console apps, ASP.NET (MVC / Web API / Web Forms), unit tests (NUnit / xUnit / MSTest), WCF services |
| Preview types | Desktop (WinForms / WPF), mobile (Xamarin), ASMX web services |
| Not transformed | Blazor UI components, Win32 DLLs without core-compatible libraries, repositories without a .NET solution, web site projects without a project file |

The .NET agent is limited to .NET-to-.NET transformation; non-.NET (e.g., Web Forms → React) uses AWS Transform custom. Containerization itself is source-code analysis and is not limited to .NET, but **as of this research (2026-09-22) an exhaustive list of supported containerization languages was not found in official documentation [Unverified]** (searched: the containerization user guide and the .NET user guide above).

### 3.3 Deployment targets and Fargate availability [Documented]

The description of the AWS managed policy `AWSTransformApplicationECSDeploymentPolicy`, used by AWS Transform to deploy containerized applications to ECS, states that it "enables AWS Transform to deploy applications to Amazon ECS **with Fargate**" (source: [AWSTransformApplicationECSDeploymentPolicy](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSTransformApplicationECSDeploymentPolicy.html)).

The permissions this policy grants are limited to ECS clusters / services / task definitions, ECR, CloudWatch Logs, and `iam:PassRole` (ECS task role / execution role). **No volume-related permissions for EBS, EFS, or FSx for ONTAP are included.** The ECS deployment AWS Transform generates therefore assumes a stateless Fargate configuration; provisioning persistent storage is outside the scope of this policy.

### 3.4 What is not in the containerization scope [Documented + Unverified]

The containerization workflow has nine steps (review security disclaimer → clone source → containerize → review artifacts → publish images → generate IaC → deploy test infrastructure → clean up test infrastructure → deploy cutover infrastructure), and none of them configure a persistent volume / data store.

**No statement that the AWS Transform containerization outputs (Helm charts / Terraform modules) emit FSx for ONTAP PV / PVC / StorageClass was found as of this research (2026-09-22) [Unverified]** (searched: the containerization user guide, the ECS deployment managed policy). Treating persistent storage as configured separately, on the destination cluster, is the reasonable reading.

### 3.5 Answers to the follow-up questions (input types and mount configuration) [Documented + Unverified]

The following answers two specific questions from primary sources. Sources are the launch blog [Containerize during migration](https://aws.amazon.com/blogs/migration-and-modernization/containerize-during-migration-replatform-applications-to-containers-with-aws-transform/) and the documents in 3.1–3.4.

**Q1: Can input other than source code (a VMware VM or a running Windows/.NET workload) be containerized?**

No. The input is always **source code** (a Git repository via CodeConnections or a zip) [Documented]. There is no path in AWS Transform containerization to containerize a VMware VM or a running server directly.

- In an end-to-end migration, **rehost (EC2) and containerize (source code) run as two parallel tracks**. A single project handles "VMs to rehost" and "source code to replatform" side by side, but a VMware VM does not enter the containerization track [Documented].
- Windows / .NET workloads also feed source code into containerization. For .NET Framework, the flow is to move to cross-platform .NET within the 3.2 scope and then containerize. **Containerization from a running server or binaries (a source-code-free path) is not AWS Transform containerization but the domain of the separate AWS App2Container tool**, which states that it "does not need source code for the application to containerize it" [Documented] (source: [What is AWS App2Container?](https://docs.aws.amazon.com/app2container/latest/UserGuide/what-is-a2c.html)). The two are separate features with different inputs.

**Q2: When containerizing to ECS can it specify an NFS/SMB mount point, and to EKS can it specify FSx for ONTAP as a PV (within the generated artifacts)?**

**As of this research (2026-09-22), that configuration was not found in the artifacts AWS Transform auto-generates [Unverified].** The ECS artifacts the launch blog illustrates are an ECS cluster (Fargate) + Application Load Balancer + Secrets Manager placeholders + CloudWatch log group; no NFS/SMB mount point or persistent volume is included. The EKS artifacts are Helm charts, stated to **require an existing EKS cluster**, with no mention of auto-generating a PV / StorageClass.

Therefore an NFS/SMB mount (ECS) or specifying FSx for ONTAP as a PV (EKS) must be built into the destination cluster separately, outside the containerization artifacts (Section 4). The artifacts can be adjusted via chat, so there is room to extend the templates by hand, but **there is no default artifact that specifies FSx for ONTAP as a PV**.

---

## 4. Integration Between FSx for ONTAP and Container Runtimes

The path to using FSx for ONTAP "after containerization" differs in mechanism and constraint by deployment target.

### 4.1 Integration on EKS (NetApp Trident) [Documented]

The AWS EKS User Guide officially points to **NetApp Trident** (a CSI-compliant driver) as the means of using FSx for ONTAP as persistent storage from EKS (source: [Use high-performance app storage with FSx for NetApp ONTAP](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)). There is no separate AWS-native CSI driver for FSx for ONTAP; that CSI driver refers to Trident. A Trident EKS add-on validated by AWS for EKS integration is also available (source: [Configure the Trident EKS add-on](https://docs.netapp.com/us-en/trident/trident-use/trident-aws-addon.html)).

Trident can provision **both block and file PVs** from FSx for ONTAP to an EKS cluster (source: [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)).

| Driver | Protocol | Volume mode | Access modes | Primary use |
|---|---|---|---|---|
| `ontap-nas` | NFS (v3 / v4.1), SMB | File | RWX possible (shared) | Workloads where multiple Pods share one PVC |
| `ontap-san` | iSCSI | Block | RWO / ROX / RWX / RWOP in block mode; RWO / RWOP in filesystem mode | Single-writer persistence, dedicated disks |

Source: [ONTAP SAN driver overview](https://docs.netapp.com/us-en/trident/trident-use/ontap-san.html). The NetApp integration guide makes the default choice "NAS driver when multiple Pods share one PVC, iSCSI block driver when not shared" (source: [Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html)).

**Operational notes (stated symmetrically)**:

- When using iSCSI (`ontap-san`), node multipath configuration can conflict with the Amazon EBS CSI driver. You must blacklist EBS devices in `multipath.conf` (source: stated in both the EKS User Guide above and the Trident documentation).
- SMB volumes are supported only with the `ontap-nas` driver, only on Windows nodes, and not with the Trident EKS add-on.
- NVMe-oF is not among the tested targets in Trident 25.02 [Documented].

### 4.2 Integration on ECS (EC2 launch type) [Documented]

The procedure for using FSx for ONTAP from ECS is documented assuming the **EC2 launch type** (source: [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)).

- Linux containers: mount the volume via NFS on the EC2 Linux instance, then bind mount into the container via the task definition `volumes` (`host.sourcePath`) and `mountPoints`.
- Windows containers: create an SMB global mapping on a domain-joined EC2 Windows instance, then bind mount similarly via the task definition.

In both cases the container runtime does not mount FSx directly; rather, **the host EC2 instance mounts it and the container bind mounts that**. Relatedly, the ECS + FSx for Windows File Server combination supports only Windows EC2 — Linux EC2 and Fargate are out of scope (source: [Use FSx for Windows File Server volumes with Amazon ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/wfsx-volumes.html)).

### 4.3 Fargate constraints [Documented]

**Fargate cannot use FSx for ONTAP as a PV / data store.** It fails on both ECS and EKS Fargate, for different reasons.

| Runtime | Constraint | Source |
|---|---|---|
| EKS Fargate | Cannot use DaemonSets, privileged Pods, or HostNetwork / HostPort. Trident is designed to run a node pod (DaemonSet) on each worker node, so it cannot start on Fargate | [Simplify compute management with AWS Fargate](https://docs.aws.amazon.com/eks/latest/userguide/fargate.html), [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html) |
| EKS Fargate (other storage) | The EFS CSI driver supports no dynamic provisioning on Fargate, only static. The EBS CSI controller can run on Fargate, but its node DaemonSet runs only on EC2. The persistent option usable on Fargate is limited to EFS (static) | [Amazon EFS CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/efs-csi.html), [Amazon EBS CSI driver](https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html) |
| ECS Fargate | Task definitions support only bind mount host volumes and EFS volumes. `dockerVolumeConfiguration` is unsupported. FSx for ONTAP is not among the supported volume types | [Amazon ECS task definition differences for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html) |

Thus "the AWS Transform ECS deployment is Fargate-capable (3.3)" and "Fargate cannot use FSx for ONTAP (this section)" are both true. **If you take the operational simplicity of Fargate you cannot attach FSx for ONTAP; if you want FSx for ONTAP persistent volumes you choose EKS EC2 worker nodes (or the ECS EC2 launch type)** — a trade-off.

---

## 5. Block Storage Use Cases

For FSx for ONTAP block (iSCSI LUN) usage, the database data store is the representative case as expected, but not the only one. Block (mostly RWO) and file (RWX possible) diverge by use.

| Pattern | Representative use cases | Basis |
|---|---|---|
| Block / iSCSI (RWO) | Database data areas, single-writer persistence, workloads demanding dedicated IOPS, middleware assuming raw block devices, per-replica dedicated volumes for a StatefulSet | "Non-shared storage uses the block / iSCSI driver" ([Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html)). Block storage is generally RWO, suited to single-node writes |
| File / NFS (RWX) | Content management shared across Pods, media processing, web serving, shared data for horizontally scaled apps | "Shared storage (multiple Pods on one PVC) uses the NAS driver" (same). Applies when a shared area is needed after containerization rather than EC2 rehost |

**Difference from the EC2 rehost path**: In an MGN-based EC2 rehost, data disks are placed as LUNs inside a FlexVol and appear to the guest OS via iSCSI (DM-Multipath / ALUA) (source: [AWS Transform FSx for ONTAP support GA verification (separate repository)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/en/atx-fsxn-ga-verification.md)). This is a different access form from a container PV. In a container environment, Trident provisions the LUN or volume through the PV / PVC / StorageClass abstraction. The EC2 rehost path is verified in a separate repository, [VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap).

---

## 6. Workload Type × Destination × Storage Pattern Fitness Matrix

Rows are the nature of the source workload, columns are the destination runtime, and cells show which storage pattern lets FSx for ONTAP be used. All based on public documentation [Documented]. Hands-on reproduction in this repository exists only for EC2 rehost [Verified]; the container paths are [Unverified].

Legend: **NFS PV** = Trident `ontap-nas` / **iSCSI PV** = Trident `ontap-san` / **iSCSI (guest)** = iSCSI mount inside the guest OS / **host NFS/SMB** = bind mount via the ECS EC2 host / **✕** = no FSx for ONTAP integration

| Source workload | EC2 rehost (MGN) | EKS (EC2 workers) | EKS Fargate | ECS (EC2 launch) | ECS Fargate |
|---|---|---|---|---|---|
| Database (dedicated disk required) | iSCSI (guest) [Verified] | iSCSI PV / NFS PV [Documented] | ✕ (no CSI) [Documented] | host NFS [Documented] | ✕ (cannot attach) [Documented] |
| Stateful .NET / Java app (single writer) | iSCSI (guest) [Documented] | iSCSI PV [Documented] | ✕ [Documented] | host NFS [Documented] | ✕ [Documented] |
| Horizontally scaled web app with shared data | iSCSI (guest) [Documented] | NFS PV (RWX) [Documented] | ✕ [Documented] | host NFS [Documented] | ✕ (EFS only) [Documented] |
| Stateless web / API | Rarely applicable (no data) | Optional (unused if not needed) | No persistence needed [Documented] | Optional | Fargate fits (no persistence needed) [Documented] |
| Windows / SMB-dependent app | iSCSI (guest) [Documented] | SMB PV (Windows nodes) [Documented] | ✕ [Documented] | host SMB (Windows EC2) [Documented] | ✕ [Documented] |

**How to read the matrix**:

- The **EC2 rehost column** is the path verified in this repository (the FSx for ONTAP block support of AWS Transform for migrations). It is a separate feature from containerization and applies to rehost only.
- The **two Fargate columns** cannot connect to FSx for ONTAP. If a workload is stateless, Fargate fits and FSx for ONTAP is not needed. Workloads that require FSx for ONTAP for a persistent area choose EC2 workers / the EC2 launch type instead of Fargate.
- **FSx for ONTAP integration in the container columns all assume a separate introduction of Trident** and is not auto-configured by AWS Transform containerization.

---

## 7. Stages to Realize It and the Split Decision

As the conclusion of the D phase (literature research in this repository), here are the stages for hands-on verification of the container-path FSx for ONTAP integration. No hands-on verification was performed this session.

1. **Containerize**: Containerize source code with AWS Transform, publish to ECR, and deploy to EKS (EC2 worker nodes).
2. **Introduce CSI**: Install NetApp Trident on the EKS cluster (Helm or the AWS-validated EKS add-on). Prepare the FSx for ONTAP file system, SVM, and credentials (Secrets Manager).
3. **Configure PV**: Create a StorageClass of `ontap-nas` (NFS / shared) or `ontap-san` (iSCSI / dedicated) as appropriate, and claim it from the application PVC.
4. **Verify**: Confirm data integrity, failover behavior, and avoidance of the EBS multipath conflict when using iSCSI.

This path has room to be split into a separate repository / Kiro project from the EC2 rehost verification (existing). The reasons are: (a) the target is source code rather than a VMware VM; (b) verification needs a different stack — an EKS cluster and Trident; (c) the FSx for ONTAP access form changes from an iSCSI guest mount to a CSI PV. Whether to split is decided after confirming feasibility through hands-on verification.

---

## 8. Unverified Items

| # | Item | Scope searched (2026-09-22) |
|---|---|---|
| C1 | Exhaustive list of containerization-supported languages | Checked the containerization user guide and the .NET user guide. The .NET range is documented, but a full list of containerization languages was not found |
| C2 | Whether AWS Transform-generated IaC emits FSx for ONTAP PVs / NFS-SMB mounts | Checked the containerization user guide, the ECS deployment managed policy, and the launch blog's generated-artifact example (ECS = cluster + ALB + Secrets Manager + CloudWatch). No persistent-storage / mount configuration stated. The reading is that it does not emit one (3.5) |
| C3 | Hands-on behavior of container-path FSx for ONTAP integration | Not performed this session. Only EC2 rehost is [Verified] via the existing report |
| C4 | Official statement that Trident is unsupported on Fargate | That Trident requires a node pod (DaemonSet) and that Fargate disallows DaemonSets / privileged pods each have sources. A single official sentence stating "Trident is unsupported on Fargate" was not found |

---

## 9. Third-Party VM → EC2 Migration (NetApp Shift Toolkit v8.0)

Sections 1–8 cover the AWS Transform-centered paths. Landing a VMware VM on AWS and placing
its data area on FSx for ONTAP is also achievable with **NetApp Shift Toolkit**, not only AWS
Transform / MGN. Relative to this repository's subject (container data stores), this provides
the "entry to migration" — the first of two stages, where a container later reaches the
FSx for ONTAP it lands on.

### 9.1 Positioning of Shift Toolkit [Documented]

Shift Toolkit is a standalone product for cross-hypervisor VM migration and disk conversion,
characterized by fast FlexClone-based conversion (source: [Shift Toolkit overview](https://docs.netapp.com/us-en/netapp-solutions/vm-migrate/migrate-overview.html)).
Its traditional targets are VMware ESXi ⇄ Microsoft Hyper-V, and ESXi → OLVM / Red Hat
OpenShift Virtualization / Proxmox VE. **This version of the overview does not list AWS / EC2
as a target.** AWS support was added as a preview feature in v8.0.

### 9.2 AWS support in v8.0 (Early Preview) [Documented][Preview]

Shift Toolkit v8.0 introduced migration to AWS as a preview feature (source: [What's New in Shift v8.0 (NetApp Community)](https://community.netapp.com/community/discussion/467669/what-s-new-in-shift-v8-0-file-to-lun-ec2-fsx-for-ontap-trident-integration-more)).

| Feature | Content | Maturity |
|---|---|---|
| EC2 with FSx for ONTAP Support | Converts a VM's **OS disks to EBS format** and its **data disks to FSx for ONTAP**, migrating to EC2. Uses ONTAP snapshots / SnapMirror / FSx for ONTAP to avoid the traditional copy process. OS disk conversion has two paths: AWS Import/Export APIs and Direct Access APIs (EBS snapshot creation) | Early Preview |
| File-to-LUN migration | Converts an existing file (e.g. VMDK) on a FlexVol **directly into a block (iSCSI LUN)**, preserving data layout | Preview |
| Shift as an Add-On for Trident | With Trident 26.06+, integrates with the CSI provisioner for OpenShift Virtualization; zero-copy cold migration | Preview |

**Early Preview constraint (must be stated)**: as of this research (2026-09-23), enabling EC2
as a target requires contacting NetApp support, per the article. Its maturity differs from the
GA AWS Transform / MGN, so state this difference when relying on it in a design.

#### Why switch from file to block (iSCSI LUN)

The article describes file-to-LUN as seamlessly moving data from file-based storage to block
(iSCSI LUN) while preserving data layout [Documented]. The motivation it gives is migration
speed and parallelism: moving from a block-backed hypervisor via direct copy or VDDK is slow,
so you storage-vMotion into an ONTAP NFS datastore first and then convert into the target's
block storage (the article's example is OpenShift Virtualization) with **high parallelism**
[Documented]. Entering migration as a file moves fast and flexibly; landing as block matches
the next operational requirement — that is the switch.

The following are not enumerated in the article; they are general motivations derived from the
ONTAP block / file split (section 5) [Documented, general reasoning].

- **File for migration, block for operation**: run the migration phase over NFS (file) for high
  parallelism and low operational cost, then take iSCSI LUN (block) in the operational phase for
  single-writer performance or a dedicated disk.
- **Workloads that require block**: database data areas, middleware that assumes a raw block
  device, dedicated volumes per StatefulSet replica, and workloads demanding dedicated IOPS —
  each suits block (mostly RWO) rather than a file share (RWX) (consistent with section 5).
- **Targets that treat VM disks as block**: OpenShift Virtualization / KubeVirt commonly handle
  VM disks as block PVCs, creating demand to convert a disk moved as a file into a block LUN on
  landing.

The use cases are shown as types, not specific customer cases. Because file-to-LUN is a preview
feature, confirming its hands-on behavior and the workloads it fits requires hands-on
verification (C5 / C6 in 9.4).

### 9.3 Connecting to the container data store (two-stage migration) [Documented]

Moving a VM to EC2 + FSx for ONTAP with Shift Toolkit v8.0 places the data on an FSx for ONTAP
volume / LUN. A container can later reach that same data (EKS via a Trident PV, ECS via
host NFS on EC2) over **iSCSI or NFS**. ONTAP's multiprotocol capability allows access to the
same volume over multiple protocols with no data migration on protocol switch (the Trident /
host NFS paths of sections 1–8 apply as-is). The v8.0 file-to-LUN feature is a concrete example
of switching something migrated as a file over to block.

The access form and the Fargate constraints (section 4) are the same whether the migration
entry is AWS Transform or Shift Toolkit. That is, Fargate cannot use FSx for ONTAP as a PV /
data area; you choose EC2 worker nodes / the EC2 launch type — the same trade-off holds on this
path too.

### 9.4 Unverified items (section 9)

| # | Item | Scope searched (2026-09-23) |
|---|---|---|
| C5 | GA timing and general-availability conditions for v8.0 AWS support | Confirmed Early Preview in the community article. GA timing and conditions for use without contacting support are not stated in the article |
| C6 | Hands-on behavior of a container reaching the post-migration data disk (FSx for ONTAP) | Not performed in this repository. Inferred from the general behavior of ONTAP multiprotocol and Trident |

---

## Reference Links

- [AWS Transform adds containerization capability during migrations (What's New, 2026-05-11)](https://aws.amazon.com/about-aws/whats-new/2026/05/aws-transform-containerization/)
- [Source code containerization (AWS Transform User Guide)](https://docs.aws.amazon.com/transform/latest/userguide/transform-containers.html)
- [Containerize during migration: Replatform applications to containers with AWS Transform (AWS Blog)](https://aws.amazon.com/blogs/migration-and-modernization/containerize-during-migration-replatform-applications-to-containers-with-aws-transform/)
- [What is AWS App2Container?](https://docs.aws.amazon.com/app2container/latest/UserGuide/what-is-a2c.html)
- [Modernizing .NET with AWS Transform](https://docs.aws.amazon.com/transform/latest/userguide/dotnet.html)
- [AWSTransformApplicationECSDeploymentPolicy (AWS Managed Policy)](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AWSTransformApplicationECSDeploymentPolicy.html)
- [Use high-performance app storage with FSx for NetApp ONTAP (EKS User Guide)](https://docs.aws.amazon.com/eks/latest/userguide/fsx-ontap.html)
- [Use Trident with Amazon FSx for NetApp ONTAP](https://docs.netapp.com/us-en/trident/trident-use/trident-fsx.html)
- [ONTAP SAN driver overview (Trident)](https://docs.netapp.com/us-en/trident/trident-use/ontap-san.html)
- [Integrate Trident](https://docs.netapp.com/us-en/trident/trident-reco/integrate-trident.html)
- [Trident architecture](https://docs.netapp.com/us-en/trident/trident-get-started/architecture.html)
- [Using Amazon Elastic Container Service with FSx for ONTAP](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/mount-ontap-ecs-containers.html)
- [Amazon ECS task definition differences for Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html)
- [Simplify compute management with AWS Fargate (EKS)](https://docs.aws.amazon.com/eks/latest/userguide/fargate.html)
- [AWS Transform FSx for ONTAP support GA verification (separate repository VMware-Migration-EC2-ONTAP)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/en/atx-fsxn-ga-verification.md)
- [Procedure: VMware → EC2 / FSx for ONTAP migration with AWS Transform (separate repository)](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap/blob/main/docs/en/aws-transform-migration-procedure.md)
- [NetApp Shift Toolkit overview (cross-hypervisor migration)](https://docs.netapp.com/us-en/netapp-solutions/vm-migrate/migrate-overview.html)
- [What's New in Shift v8.0: File-to-LUN, EC2 + FSx for ONTAP, Trident (NetApp Community)](https://community.netapp.com/community/discussion/467669/what-s-new-in-shift-v8-0-file-to-lun-ec2-fsx-for-ontap-trident-integration-more)
